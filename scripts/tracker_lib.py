# -*- coding: utf-8 -*-
"""Shared helpers for the daily meme tracker and D+3 backtest."""
from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import paths as P

TRACKER_FIELDS = [
    "date", "meme", "canonical_id", "verdict", "score",
    "score_heat", "score_trend", "score_share", "score_competition", "score_window",
    "primary_heat_metric", "primary_heat_value", "primary_heat_date", "primary_heat_source",
    "x_7d_posts", "x_7d_range", "x_7d_source",
    "viralremix_new_videos", "viralremix_date", "viralremix_complete",
    "cc_tag", "cc_region", "cc_rank_7d", "cc_rank_30d", "cc_index_30d", "cc_index_30d_date",
    "remix_median_share_rate", "remix_n", "remix_platform",
    "ignite_date", "days_hot", "peak_status",
    "window", "part", "source_tag", "notes",
]

# How the 2026-11-10 v5 pack chose a primary heat series for trend/peak.
# Unknown future memes default to viralremix_new_videos if that series exists,
# else x_posts, else cc_index_30d, else none_daily_volume. Never invent values.
PRIMARY_BY_NAME = {
    "Shoulder Carry": ("viralremix_new_videos", "ViralRemix daily board new videos/day【第三方读数】"),
    "Can I Ride": ("viralremix_new_videos", "ViralRemix daily board new videos/day【第三方读数】"),
    "Ba Ba Ba Dance": ("viralremix_new_videos", "ViralRemix daily board new videos/day【第三方读数】"),
    "Shaking Head": ("viralremix_new_videos", "ViralRemix daily board new videos/day【第三方读数】"),
    "Then I Walk In": ("viralremix_new_videos", "ViralRemix daily board new videos/day【第三方读数】"),
    "Turning My Mom Into Me": ("viralremix_new_videos", "ViralRemix daily board new videos/day【第三方读数】"),
    "Bicep Heart": ("x_posts", "X get_posts_counts_recent 日发帖（报告用它判断高峰）【已核实】"),
    "Malfoid": ("x_posts", "X get_posts_counts_recent 日发帖【已核实】"),
    "#lastchristmas": ("cc_index_30d", "Creative Center US News&Entertainment 30 日相对指数 0–100【已核实·CC相对指数】"),
    "冬日恐悚 / 悬疑反转": ("cc_index_30d", "Creative Center #tiktokscaryhorrorcontest 30 日相对指数（主标签）；#tiktokthrillermysterycontest 另有一条曲线【已核实·CC相对指数】"),
    "#imsosorry": ("cc_index_30d", "Creative Center US 30 日相对指数【已核实·CC相对指数】"),
    "#damehombro": ("cc_index_30d", "Creative Center US 30 日相对指数【已核实·CC相对指数】"),
    "#halloweentransition": ("cc_index_30d", "Creative Center US 30 日相对指数【已核实·CC相对指数】"),
    "Cat on Ultra Bee": ("none_daily_volume", "无 ViralRemix 日榜，X 近 7 日完整日为 0；没有可用于回测的全站日热度序列。"),
    "Flamingo Float": ("none_daily_volume", "无 ViralRemix 日榜；报告用二创发布日判断高峰，不是全站日产量。"),
    "Grandpa Fish": ("none_daily_volume", "无 ViralRemix 日榜；报告用二创发布日判断高峰，不是全站日产量。"),
    "Flower Bouquet With Face": ("viralremix_new_videos", "ViralRemix daily board new videos/day【第三方读数】"),
    "Pet Rock Dance": ("viralremix_new_videos", "ViralRemix daily board new videos/day【第三方读数】"),
    "Police Chase AI": ("viralremix_new_videos", "ViralRemix daily board new videos/day【第三方读数】"),
    "Pimpwalk Entrance": ("viralremix_new_videos", "ViralRemix daily board new videos/day【第三方读数】"),
    "Deck the Halls Dance": ("none_daily_volume", "无 ViralRemix 日榜；Turnly 创作者计数不是全站日产量。"),
    "#housewife": ("cc_index_30d", "Creative Center US 30 日相对指数【已核实·CC相对指数】"),
    "#meimei": ("cc_index_30d", "Creative Center GB 30 日相对指数（7 日曲线在 CA）【已核实·CC相对指数】"),
    "#a2olite": ("cc_index_30d", "Creative Center KR 30 日相对指数【已核实·CC相对指数】"),
    "#angelofmydreams": ("cc_index_30d", "Creative Center US 30 日相对指数【已核实·CC相对指数】"),
    "#mandem": ("cc_index_30d", "Creative Center AU 30 日相对指数【已核实·CC相对指数】"),
}

CC_PRIMARY_REGION = {
    "#lastchristmas": "US",
    "冬日恐悚 / 悬疑反转": "US",
    "#imsosorry": "US",
    "#damehombro": "US",
    "#halloweentransition": "US",
    "#housewife": "US",
    "#meimei": "GB",
    "#a2olite": "KR",
    "#angelofmydreams": "US",
    "#mandem": "AU",
}

CC_PRIMARY_TAG = {
    "#lastchristmas": "lastchristmas",
    "冬日恐悚 / 悬疑反转": "tiktokscaryhorrorcontest",
    "#imsosorry": "imsosorry",
    "#damehombro": "damehombro",
    "#halloweentransition": "halloweentransition",
    "#housewife": "housewife",
    "#meimei": "meimei",
    "#a2olite": "a2olite",
    "#angelofmydreams": "angelofmydreams",
    "#mandem": "mandem",
}

HISTORY_DIR = P.DATA_DIR
DEFAULT_TRACKER = P.TRACKER
DEFAULT_BACKTEST_JSON = P.BACKTEST_JSON
DEFAULT_BACKTEST_CSV = P.BACKTEST_CSV


def is_complete(v) -> bool:
    return str(v) in ("True", "true", "1")


def read_csv(path: Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8-sig")
    return list(csv.DictReader(text.splitlines()))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def index_heat(rows: list[dict]) -> dict:
    by = defaultdict(list)
    for r in rows:
        by[(r["meme"], r["metric"])].append(r)
    return by


def last_complete(heat_by, meme, metric, on_or_before: str | None = None):
    vs = [r for r in heat_by.get((meme, metric), []) if is_complete(r.get("complete"))]
    if on_or_before:
        vs = [r for r in vs if r.get("date", "") <= on_or_before]
    vs.sort(key=lambda r: r.get("date", ""))
    return vs[-1] if vs else None


def complete_on(heat_by, meme, metric, on_date: str):
    for r in heat_by.get((meme, metric), []):
        if r.get("date") == on_date and is_complete(r.get("complete")):
            return r
    return None


def x_7d_complete_sum(heat_by, meme: str, end: date):
    start = end - timedelta(days=6)
    vs = [
        r for r in heat_by.get((meme, "x_posts"), [])
        if is_complete(r.get("complete")) and start.isoformat() <= r.get("date", "") <= end.isoformat()
    ]
    if not vs:
        return "", "", ""
    vs.sort(key=lambda r: r["date"])
    s = sum(float(r["value"]) for r in vs)
    val = str(int(s) if s == int(s) else s)
    rng = f"{vs[0]['date']}..{vs[-1]['date']}"
    src = (
        f"X get_posts_counts_recent，仅计入 complete=true 的 UTC 自然日"
        f"（n={len(vs)}，{vs[0]['date']}–{vs[-1]['date']}）。不完整日已排除，因此可能不满 7 天。"
    )
    return val, rng, src


def remix_medians(remix_rows: list[dict], platform: str = "TikTok") -> dict:
    share = defaultdict(list)
    for r in remix_rows:
        if r.get("platform") == platform and r.get("share_rate"):
            try:
                share[r["meme"]].append(float(r["share_rate"]))
            except ValueError:
                continue
    out = {}
    for meme, vs in share.items():
        out[meme] = (f"{statistics.median(vs):.6f}", str(len(vs)))
    return out


def _norm_cc_tag(tag: str) -> str:
    t = (tag or "").strip().lower()
    return t if t.startswith("#") else f"#{t}"


def cc_last_index(cc_rows: list[dict], tag: str, period: str = "30", region: str | None = None):
    want = _norm_cc_tag(tag)
    vs = []
    for r in cc_rows:
        status = (r.get("status") or "found").lower()
        if status not in ("", "found"):
            continue
        if _norm_cc_tag(r.get("hashtag") or "") != want:
            continue
        if str(r.get("period_days")) != str(period):
            continue
        if region and (r.get("region") or "US") != region:
            continue
        if not r.get("date") or r.get("value") in ("", None):
            continue
        vs.append(r)
    vs.sort(key=lambda r: r["date"])
    return vs[-1] if vs else None


def cc_index_on(cc_rows: list[dict], tag: str, on_date: str, period: str = "30"):
    for r in cc_rows:
        if (
            r.get("hashtag") == tag
            and str(r.get("period_days")) == str(period)
            and r.get("status") == "found"
            and r.get("date") == on_date
            and r.get("value") not in ("", None)
        ):
            return r
    return None


def cc_rank(rank_rows: list[dict], tag: str, period, region: str | None = None) -> str:
    h = tag if str(tag).startswith("#") else f"#{tag}"
    # Prefer the requested region; fall back to the first match.
    hits = []
    for r in rank_rows:
        if r.get("hashtag", "").lower() == h.lower() and str(r.get("period_days")) == str(period):
            if region and (r.get("region") or "") == region:
                return r.get("rank", "")
            hits.append(r)
    if region:
        return ""
    return hits[0].get("rank", "") if hits else ""


def infer_primary(name: str, heat_by, cc_tag: str):
    if name in PRIMARY_BY_NAME:
        return PRIMARY_BY_NAME[name]
    if last_complete(heat_by, name, "viralremix_new_videos"):
        return "viralremix_new_videos", "ViralRemix daily board new videos/day【第三方读数】（按默认规则，因该梗不在预置表里）"
    if last_complete(heat_by, name, "x_posts"):
        return "x_posts", "X get_posts_counts_recent 日发帖【已核实】（按默认规则）"
    if cc_tag:
        return "cc_index_30d", "Creative Center 30 日相对指数【已核实·CC相对指数】（按默认规则）"
    return "none_daily_volume", "没有可用的全站日热度序列，回测会记为数据不足。"


def build_row(meme_obj: dict, report_date: str, heat_by, remix_med, cc_rows, rank_rows, notes: str = "") -> dict:
    name = meme_obj["name"]
    scores = meme_obj.get("scores") or {}
    rd = date.fromisoformat(report_date)
    cc_tag = CC_PRIMARY_TAG.get(name, "")
    if not cc_tag:
        tags = meme_obj.get("cc_hashtags") or []
        if tags:
            cc_tag = tags[0].lstrip("#")
    metric, metric_src = infer_primary(name, heat_by, cc_tag)
    vr = last_complete(heat_by, name, "viralremix_new_videos", report_date)
    x7, x7range, x7src = x_7d_complete_sum(heat_by, name, rd)

    cc_idx = cc_idx_date = cc_r7 = cc_r30 = ""
    cc_region_pref = CC_PRIMARY_REGION.get(name) or meme_obj.get("cc_region") or "US"
    if cc_tag:
        cc_region_pref = CC_PRIMARY_REGION.get(name) or meme_obj.get("cc_region") or "US"
        last = cc_last_index(cc_rows, cc_tag, "30", region=cc_region_pref) or cc_last_index(cc_rows, cc_tag, "30")
        if last:
            cc_idx, cc_idx_date = last.get("value", ""), last.get("date", "")
            cc_region_pref = last.get("region") or cc_region_pref
        cc_r7 = cc_rank(rank_rows, cc_tag, "7", region=cc_region_pref)
        cc_r30 = cc_rank(rank_rows, cc_tag, "30", region=cc_region_pref)

    ph_val = ph_date = ""
    if metric == "viralremix_new_videos" and vr:
        ph_val, ph_date = vr.get("value", ""), vr.get("date", "")
    elif metric == "x_posts":
        lastx = last_complete(heat_by, name, "x_posts", report_date)
        if lastx:
            ph_val, ph_date = lastx.get("value", ""), lastx.get("date", "")
    elif metric == "cc_index_30d":
        ph_val, ph_date = cc_idx, cc_idx_date

    med, nshare = remix_med.get(name, ("", ""))

    return {
        "date": report_date,
        "meme": name,
        "canonical_id": meme_obj.get("id", ""),
        "verdict": meme_obj.get("verdict", ""),
        "score": scores.get("total", ""),
        "score_heat": scores.get("热度", ""),
        "score_trend": scores.get("趋势", ""),
        "score_share": scores.get("分享率", ""),
        "score_competition": scores.get("竞争", ""),
        "score_window": scores.get("窗口", ""),
        "primary_heat_metric": metric,
        "primary_heat_value": ph_val,
        "primary_heat_date": ph_date,
        "primary_heat_source": metric_src,
        "x_7d_posts": x7,
        "x_7d_range": x7range,
        "x_7d_source": x7src,
        "viralremix_new_videos": vr.get("value", "") if vr else "",
        "viralremix_date": vr.get("date", "") if vr else "",
        "viralremix_complete": vr.get("complete", "") if vr else "",
        "cc_tag": cc_tag,
        "cc_region": (cc_region_pref if cc_tag else ""),
        "cc_rank_7d": cc_r7,
        "cc_rank_30d": cc_r30,
        "cc_index_30d": cc_idx,
        "cc_index_30d_date": cc_idx_date,
        "remix_median_share_rate": med,
        "remix_n": nshare,
        "remix_platform": "TikTok" if nshare else "",
        "ignite_date": meme_obj.get("ignite_date", ""),
        "days_hot": meme_obj.get("days_hot", ""),
        "peak_status": meme_obj.get("peak_status_short") or meme_obj.get("peak_status", ""),
        "window": meme_obj.get("window", ""),
        "part": meme_obj.get("part", ""),
        "source_tag": meme_obj.get("source_tag", ""),
        "notes": notes,
    }


def upsert_rows(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    """Replace rows that share the same (date, canonical_id or meme). Keep other dates."""
    def key(r):
        return (r.get("date", ""), r.get("canonical_id") or r.get("meme", ""))

    keep = [r for r in existing if key(r) not in {key(n) for n in new_rows}]
    all_rows = keep + new_rows
    all_rows.sort(key=lambda r: (r.get("date", ""), str(r.get("score") or "0")), reverse=False)
    return all_rows


def to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
