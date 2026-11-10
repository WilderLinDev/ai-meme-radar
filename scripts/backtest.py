#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backtest 做 recommendations: still rising at D+3?

Rule (as agreed): a meme recommended 做 on report date D is
  对      if its primary heat metric on date D+3 is complete and strictly greater
          than the baseline stored on the D tracker row;
  错      if that D+3 point exists, is complete, and is less than or equal to the baseline;
  数据不足 if there is no usable baseline, the metric has no daily series
          (none_daily_volume), or the complete D+3 point is missing.

The baseline is the primary_heat_value recorded on the D row (the number the
report actually used). The D+3 point is looked up in --heat CSVs when provided,
otherwise in later tracker rows / the CC columns of the tracker.

Output is written for scripts/build_report.py:
  data/backtest-latest.json
  data/backtest-latest.csv
JSON keys used by the report:
  summary_zh          — short subsection to place after the 总排名表
  per_meme[].card_line_zh — one line for that meme's 结论卡
  hit_rate, correct, wrong, insufficient, eligible, horizon_days
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths as P  # noqa: E402
import tracker_lib as lib  # noqa: E402

HORIZON = 3


def load_heat_files(paths: list[str]) -> dict:
    by = defaultdict(list)
    seen = set()
    for p in paths:
        if not p:
            continue
        for r in lib.read_csv(p):
            key = (r.get("meme"), r.get("metric"), r.get("date"), r.get("source"))
            if key in seen:
                continue
            seen.add(key)
            by[(r.get("meme"), r.get("metric"))].append(r)
    return by


def lookup_d3(metric: str, meme: str, tag: str, d3: date, heat_by, cc_rows, tracker_rows):
    """Return (value, date, source) for a complete D+3 observation, or (None, '', reason)."""
    d3s = d3.isoformat()
    if metric == "viralremix_new_videos":
        hit = lib.complete_on(heat_by, meme, "viralremix_new_videos", d3s)
        if hit:
            return hit["value"], d3s, hit.get("source") or "ViralRemix"
        # fall back to a later tracker row dated d3
        for r in tracker_rows:
            if r.get("meme") == meme and r.get("date") == d3s and r.get("viralremix_date") == d3s:
                if lib.is_complete(r.get("viralremix_complete")) and r.get("viralremix_new_videos"):
                    return r["viralremix_new_videos"], d3s, "tracker.viralremix_new_videos"
        return None, "", f"没有 {d3s} 的完整 ViralRemix 日点"
    if metric == "x_posts":
        hit = lib.complete_on(heat_by, meme, "x_posts", d3s)
        if hit:
            return hit["value"], d3s, hit.get("source") or "X"
        for r in tracker_rows:
            if r.get("meme") == meme and r.get("date") == d3s and r.get("primary_heat_metric") == "x_posts":
                if r.get("primary_heat_date") == d3s and r.get("primary_heat_value"):
                    return r["primary_heat_value"], d3s, "tracker.x_posts"
        return None, "", f"没有 {d3s} 的完整 X 日发帖点"
    if metric == "cc_index_30d":
        if tag:
            hit = lib.cc_index_on(cc_rows, tag, d3s, "30")
            if hit:
                return hit["value"], d3s, "Creative Center 30d index"
        for r in tracker_rows:
            if r.get("meme") == meme and r.get("cc_index_30d_date") == d3s and r.get("cc_index_30d"):
                return r["cc_index_30d"], d3s, "tracker.cc_index_30d"
        return None, "", f"没有 {d3s} 的完整 Creative Center 30 日指数"
    if metric == "none_daily_volume":
        return None, "", "该梗没有可用于回测的全站日热度序列"
    return None, "", f"未知主热度口径 {metric}"


def card_line(result: str, rec_date: str, d3: str, base, later, reason: str) -> str:
    if result == "数据不足":
        return f"回测：数据不足（推荐日 {rec_date}，D+3 为 {d3}；{reason}）。"
    arrow = "仍在涨" if result == "对" else "未继续涨"
    return (
        f"回测：{result}（{arrow}；推荐日 {rec_date} 主热度 {base} → {d3} 的 {later}）。"
    )


def summary_zh(payload: dict) -> str:
    n = payload["eligible"]
    c, w, u = payload["correct"], payload["wrong"], payload["insufficient"]
    hr = payload["hit_rate"]
    hr_s = f"{hr:.0%}" if hr is not None else "还算不了"
    lines = [
        f"回测（推荐后 {payload['horizon_days']} 天主热度是否仍在涨）：可判断 {n} 条，对 {c}，错 {w}，命中率 {hr_s}；数据不足 {u} 条。",
        payload["rule_zh"],
    ]
    if n == 0:
        lines.append(
            "目前历史表里还没有满 D+3 窗口的「做」推荐，所以还没有对错可报。"
            "从今天起把每天的 pack 追加进 tracker 后，满三天就能开始出命中率。"
        )
    return "\n".join(lines)


def run(tracker_path: Path, heat_paths: list[str], cc_paths: list[str], as_of: str | None):
    tracker = lib.read_csv(tracker_path) if tracker_path.exists() else []
    heat_by = load_heat_files(heat_paths)
    cc_rows = []
    for p in cc_paths:
        cc_rows.extend(lib.read_csv(p))

    recs = [r for r in tracker if r.get("verdict") == "做"]
    # one result per (date, meme); if a date was upserted twice, last wins
    uniq = {}
    for r in recs:
        uniq[(r.get("date"), r.get("canonical_id") or r.get("meme"))] = r
    recs = sorted(uniq.values(), key=lambda r: (r.get("date", ""), r.get("meme", "")))

    results = []
    today = date.fromisoformat(as_of) if as_of else date.today()

    for r in recs:
        try:
            d = date.fromisoformat(r["date"])
        except (KeyError, ValueError):
            continue
        d3 = d + timedelta(days=HORIZON)
        metric = r.get("primary_heat_metric") or ""
        baseline = lib.to_float(r.get("primary_heat_value"))
        reason_parts = []
        result = "数据不足"
        later_v = later_date = later_src = ""

        if d3 > today:
            reason_parts.append(f"D+3={d3.isoformat()} 还没到（今天按 {today.isoformat()} 计）")
        if metric in ("", "none_daily_volume", "unknown"):
            reason_parts.append(r.get("primary_heat_source") or "没有可用于回测的全站日热度序列")
        elif baseline is None:
            reason_parts.append("推荐日行上没有主热度基线值")
        else:
            val, later_date, later_src = lookup_d3(
                metric, r.get("meme", ""), r.get("cc_tag", ""), d3, heat_by, cc_rows, tracker
            )
            later = lib.to_float(val)
            if later is None:
                reason_parts.append(later_src or f"没有 {d3.isoformat()} 的完整主热度")
            else:
                later_v = val
                result = "对" if later > baseline else "错"
                reason_parts = [
                    f"基线 {r.get('primary_heat_date')} 的 {r.get('primary_heat_value')} → {later_date} 的 {later_v}"
                    + ("" if later > baseline else "（未严格上升）")
                ]

        reason = "；".join(reason_parts)
        results.append({
            "meme": r.get("meme", ""),
            "canonical_id": r.get("canonical_id", ""),
            "recommend_date": r.get("date", ""),
            "verdict": r.get("verdict", ""),
            "score": r.get("score", ""),
            "primary_heat_metric": metric,
            "baseline_value": r.get("primary_heat_value", ""),
            "baseline_date": r.get("primary_heat_date", ""),
            "d3_date": d3.isoformat(),
            "d3_value": later_v,
            "d3_source": later_src if later_v else "",
            "result": result,
            "reason": reason,
            "card_line_zh": card_line(result, r.get("date", ""), d3.isoformat(), r.get("primary_heat_value") or "—", later_v or "—", reason),
        })

    eligible = [x for x in results if x["result"] in ("对", "错")]
    correct = sum(1 for x in eligible if x["result"] == "对")
    wrong = sum(1 for x in eligible if x["result"] == "错")
    insufficient = sum(1 for x in results if x["result"] == "数据不足")
    hit_rate = (correct / len(eligible)) if eligible else None

    payload = {
        "as_of": today.isoformat(),
        "horizon_days": HORIZON,
        "rule": "做 on day D is 对 iff complete primary heat on D+3 is strictly greater than the baseline stored on the D tracker row.",
        "rule_zh": "口径：某天推荐「做」的梗，若 D+3 当天有完整主热度，且严格高于推荐日行里记下的基线，记为对；有完整点但不高于基线记为错；没有日序列、基线或 D+3 完整点记为数据不足。不插值。",
        "tracker": str(tracker_path),
        "eligible": len(eligible),
        "correct": correct,
        "wrong": wrong,
        "insufficient": insufficient,
        "recommended_do": len(results),
        "hit_rate": hit_rate,
        "per_meme": results,
    }
    payload["summary_zh"] = summary_zh(payload)
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description="Backtest 做 recommendations at D+3.")
    p.add_argument("--tracker", default=str(lib.DEFAULT_TRACKER))
    p.add_argument("--heat", action="append", default=[], help="heat CSV, can be passed more than once")
    p.add_argument("--cc", action="append", default=[], help="Creative Center trend CSV, repeatable")
    p.add_argument("--as-of", dest="as_of", help="YYYY-MM-DD, default today (box local)")
    p.add_argument("--json-out", default=str(lib.DEFAULT_BACKTEST_JSON))
    p.add_argument("--csv-out", default=str(lib.DEFAULT_BACKTEST_CSV))
    args = p.parse_args()

    # Default heat/cc from the 11/10 report folder if present and none passed
    if not args.heat:
        default_heat = P.resolve("2026-11-10", "heat.csv", "heat_2026-11-10.csv")
        if default_heat.exists():
            args.heat = [str(default_heat)]
    if not args.cc:
        default_cc = P.resolve(
            "2026-11-10", "cc-hashtag-trends.csv", "cc_hashtag_trends_2026-11-10.csv"
        )
        if default_cc.exists():
            args.cc = [str(default_cc)]

    payload = run(Path(args.tracker), args.heat, args.cc, args.as_of)
    json_out = Path(args.json_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    csv_fields = [
        "recommend_date", "meme", "canonical_id", "verdict", "score",
        "primary_heat_metric", "baseline_value", "baseline_date",
        "d3_date", "d3_value", "d3_source", "result", "reason", "card_line_zh",
    ]
    lib.write_csv(Path(args.csv_out), csv_fields, payload["per_meme"])

    print(payload["summary_zh"])
    print()
    for r in payload["per_meme"]:
        print(f"  {r['result']:6}  {r['recommend_date']}  {r['meme']:28}  {r['reason']}")
    print(f"\nwrote {json_out}")
    print(f"wrote {args.csv_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
