#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Incremental Lark Base sync: 8-region snapshots, merged curves, audience, tracker upserts.

Writes create/update batches under data/lark-batches/. Off unless --sync-lark.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths as P  # noqa: E402
import sync_lark as S  # noqa: E402

AS_OF = "2026-11-10"
APP = S.APP_TOKEN
BATCH_DIR = S.BATCH_DIR


def parse_index(raw: str):
    """Parse '1 (800.56)' -> (rank, index)."""
    s = (raw or "").strip()
    m = re.search(r"\(([\d.]+)\)", s)
    idx = float(m.group(1)) if m else None
    m2 = re.match(r"(\d+)", s)
    rank = int(m2.group(1)) if m2 else None
    return rank, idx


def load_tag_ids(as_of: str = AS_OF) -> dict[str, str]:
    ids = S.load_tag_ids()
    for path in [
        P.resolve(as_of, "cc-hashtag-trends.csv", f"cc_hashtag_trends_{as_of}_merged.csv", f"cc_hashtag_trends_{as_of}.csv"),
        P.resolve(as_of, "cc-detail-targets.csv", f"cc_detail_targets_{as_of}.csv"),
    ]:
        if not path.exists():
            continue
        for r in S.read_csv(path):
            tid = (r.get("detail_id") or S.extract_detail_id(r.get("detail_url") or r.get("url_30") or r.get("url_7") or "") or "").strip()
            tag = (r.get("hashtag") or "").lstrip("#").lower()
            if tid and tag:
                ids[tag] = tid
    detail = P.resolve(as_of, "cc-hashtag-detail.json", f"cc_hashtag_detail_{as_of}.json")
    if detail.exists():
        for d in json.loads(detail.read_text(encoding="utf-8")):
            tag = (d.get("hashtag") or "").lstrip("#").lower()
            tid = str(d.get("detail_id") or "")
            if tag and tid:
                ids[tag] = tid
    return ids


def build_cc_rank_snapshot(as_of: str, tag_ids: dict, prev_ranks=None) -> list[dict]:
    path = P.resolve(as_of, "cc-top100.csv", f"{as_of}_NewsEnt_top100_all.csv")
    if not path.exists():
        raise FileNotFoundError(path)
    raw_rows = S.read_csv(path)
    # per-region 7 vs 30 presence
    present = defaultdict(set)
    for r in raw_rows:
        tag = (r.get("hashtag") or "").strip()
        region = (r.get("region") or "").strip()
        period = S.period_label(r.get("period_days"))
        if tag and region and period:
            present[(tag, region)].add(period)
    rows = []
    for r in raw_rows:
        period = S.period_label(r.get("period_days"))
        tag = (r.get("hashtag") or "").strip()
        region = (r.get("region") or "").strip() or "US"
        rank = S.parse_number(r.get("rank"))
        posts, posts_raw = S.parse_count(r.get("posts"))
        views, views_raw = S.parse_count(r.get("views"))
        ratio = None
        if posts and views and posts != 0:
            ratio = round(views / posts, 2)
        key_tag = tag.lstrip("#").lower()
        tid = (r.get("detail_id") or "").strip() or tag_ids.get(key_tag, "")
        period_days = "7" if period == "7日" else "30" if period == "30日" else ""
        url = S.detail_url(tid, region, period_days)
        pers = present.get((tag, region), set())
        if pers == {"7日"}:
            flag, is_new = "NEW_7D", True
        elif pers == {"30日"}:
            flag, is_new = "FADE_30D", False
        elif pers == {"7日", "30日"}:
            flag, is_new = "SUSTAIN", False
        else:
            flag, is_new = None, None
        key = f"{as_of}|{region}|{period}|{rank}|{tag}"
        rec = {
            "去重键": key,
            "抓取日期": S.date_to_ms(as_of),
            "地区": region if region in S.REGIONS else None,
            "筛选行业": "News & Entertainment",
            "行业": (r.get("industry") or "").strip(),
            "周期": period,
            "排名": rank,
            "话题": tag,
            "发帖数": posts,
            "发帖数原文": posts_raw,
            "播放量": views,
            "播放量原文": views_raw,
            "播放/发帖": ratio,
            "详情ID": tid,
            "详情链接": url,
            "是否新进7日": is_new,
            "7日30日代理": flag,
        }
        # rank_change is blank in the source; omit rather than invent
        rows.append(S.fields_clean(rec))
    return rows


def build_cc_hashtag_curve(as_of: str, tag_ids: dict) -> list[dict]:
    path = P.resolve(
        as_of,
        "cc-hashtag-trends.csv",
        f"cc_hashtag_trends_{as_of}_merged.csv",
        f"cc_hashtag_trends_{as_of}.csv",
    )
    rows = []
    for r in S.read_csv(path):
        status = (r.get("status") or "found").strip().lower()
        if status not in ("", "found"):
            continue
        if not r.get("date") or r.get("value") in (None, ""):
            continue
        period = S.period_label(r.get("period_days"))
        tag_raw = (r.get("hashtag") or "").strip()
        tag = tag_raw.lstrip("#")  # match already-loaded keys
        region = (r.get("region") or S.extract_region(r.get("detail_url") or "") or "US").strip()
        tid = (r.get("detail_id") or S.extract_detail_id(r.get("detail_url") or "") or tag_ids.get(tag.lower(), ""))
        key = f"{as_of}|{tag}|{region}|{period}|{r['date']}"
        rows.append(S.fields_clean({
            "去重键": key,
            "抓取日期": S.date_to_ms(as_of),
            "话题": tag,
            "地区": region if region in S.REGIONS else None,
            "周期": period,
            "日期": S.date_to_ms(r["date"]),
            "热度指数": S.parse_number(r.get("value")),
            "详情ID": tid,
            "详情链接": r.get("detail_url") or S.detail_url(tid, region, "7" if period == "7日" else "30"),
        }))
    return rows


def build_cc_hashtag_audience(as_of: str, tag_ids: dict | None = None) -> list[dict]:
    path = P.resolve(as_of, "cc-hashtag-detail.json", f"cc_hashtag_detail_{as_of}.json")
    if not path.exists():
        return []
    details = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for d in details:
        tag_raw = (d.get("hashtag") or "").strip()
        tag = tag_raw if tag_raw.startswith("#") else f"#{tag_raw}"
        tag_key = tag.lstrip("#")
        region = (d.get("region") or "US").strip()
        period = S.period_label(d.get("period_days"))
        tid = str(d.get("detail_id") or (tag_ids or {}).get(tag_key, "") or "")
        for a in d.get("age") or []:
            bucket = a.get("bucket") or ""
            key = f"{as_of}|{tag_key}|{region}|{period}|年龄|{bucket}"
            rows.append(S.fields_clean({
                "去重键": key,
                "抓取日期": S.date_to_ms(as_of),
                "话题": tag,
                "地区": region if region in S.REGIONS else None,
                "周期": period,
                "维度": "年龄",
                "分组": bucket,
                "占比": S.parse_number(a.get("pct")),
                "详情ID": tid,
                "数值说明": "年龄占比（%）",
            }))
        for c in d.get("regions") or []:
            country = c.get("country") or ""
            rank, idx = parse_index(c.get("pct_or_rank") or "")
            key = f"{as_of}|{tag_key}|{region}|{period}|地区|{country}"
            rows.append(S.fields_clean({
                "去重键": key,
                "抓取日期": S.date_to_ms(as_of),
                "话题": tag,
                "地区": region if region in S.REGIONS else None,
                "周期": period,
                "维度": "地区",
                "分组": country,
                "人气指数": idx,
                "详情ID": tid,
                "数值说明": f"地区人气指数（不是占比）" + (f"；排名 {rank}" if rank else ""),
            }))
    return rows


def remix_path(as_of: str) -> Path:
    return P.resolve(
        as_of,
        "remix-stats.csv",
        f"remix_stats_{as_of}_run2.csv",
        f"remix_stats_{as_of}.csv",
    )


def write_all(as_of: str, existing_map: dict[str, dict[str, str]], skip_tables: set[str]):
    tag_ids = load_tag_ids(as_of)
    builders = {
        "cc_rank_snapshot": lambda: build_cc_rank_snapshot(as_of, tag_ids),
        "cc_hashtag_curve": lambda: build_cc_hashtag_curve(as_of, tag_ids),
        "cc_hashtag_audience": lambda: build_cc_hashtag_audience(as_of, tag_ids),
        "meme_daily_tracker": S.build_meme_daily_tracker,
        "remix_videos": lambda: S.build_remix_videos(as_of),
        "backtest": S.build_backtest,
        "watchlist": S.build_watchlist,
    }
    out_dir = BATCH_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for key, builder in builders.items():
        if key in skip_tables:
            continue
        records = builder()
        id_map = existing_map.get(key) or {}
        existing_keys = set(id_map.keys())
        to_create, to_update = [], []
        for rec in records:
            fields = rec["fields"] if "fields" in rec else rec
            dk = fields.get("去重键")
            if dk in existing_keys:
                # For snapshot: only push the new proxy fields if present
                # For tracker/backtest: full field update (values changed)
                if key == "cc_rank_snapshot":
                    # values were confirmed identical; only backfill new fields
                    patch = {}
                    for f in ("是否新进7日", "7日30日代理"):
                        if f in fields:
                            patch[f] = fields[f]
                    if patch:
                        to_update.append({"record_id": id_map[dk], "fields": patch})
                elif key in {"meme_daily_tracker", "backtest"}:
                    to_update.append({"record_id": id_map[dk], "fields": {k: v for k, v in fields.items() if k != "去重键"}})
                # remix/watchlist/curves unchanged → skip
            else:
                to_create.append({"fields": fields})
        # write chunks
        def dump(kind, recs, size=80):
            paths = []
            for i, chunk in enumerate(S.chunk(recs, size), 1):
                p = out_dir / f"{as_of}-delta-{key}.{kind}.{i:02d}.json"
                p.write_text(json.dumps(chunk, ensure_ascii=False), encoding="utf-8")
                paths.append(str(p))
            return paths
        c_paths = dump("create", to_create, 80)
        u_paths = dump("update", to_update, 80)
        summary[key] = {
            "built": len(records),
            "create": len(to_create),
            "update": len(to_update),
            "skipped_unchanged": len(records) - len(to_create) - len(to_update),
            "create_files": c_paths,
            "update_files": u_paths,
        }
        print(f"{S.TABLES[key]['name']:10} built={len(records):4} create={len(to_create):4} update={len(to_update):4} files_c={len(c_paths)} files_u={len(u_paths)}")
    (out_dir / f"{as_of}-delta-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _build_remix(as_of: str):
    # Prefer the dated remix file but keep the same 去重键 (as_of|link).
    remix_path(as_of)
    return S.build_remix_videos(as_of)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Incremental Lark Base batches. Off unless --sync-lark.")
    parser.add_argument("--as-of", default=AS_OF)
    parser.add_argument(
        "--existing-keys",
        help="JSON object of table_key -> {去重键: record_id}. Required when sync is on.",
    )
    P.add_lark_flags(parser)
    args = parser.parse_args()
    if not P.lark_enabled(args.sync_lark, args.no_lark):
        print(P.lark_disabled_message())
        return 0
    if args.existing_keys:
        keys_path = Path(args.existing_keys)
    else:
        candidates = [
            P.LARK_BATCH_DIR / f"{args.as_of}-existing-keys.json",
            P.LEGACY_LARK / "history" / "lark_batches" / f"existing_keys_{args.as_of}_run2.json",
            P.LEGACY_LARK / "history" / "lark_batches" / "existing_keys.json",
        ]
        keys_path = next((p for p in candidates if p.exists()), candidates[0])
    if not keys_path.exists():
        raise SystemExit(f"existing keys file not found: {keys_path}")
    existing = json.loads(keys_path.read_text(encoding="utf-8"))
    summary = write_all(args.as_of, existing, skip_tables={"digest_index"})
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk in ("built", "create", "update", "skipped_unchanged")} for k, v in summary.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
