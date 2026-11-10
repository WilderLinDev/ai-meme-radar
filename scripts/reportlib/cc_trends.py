# -*- coding: utf-8 -*-
"""Load Creative Center hashtag-detail popularity curves.

CSV columns: hashtag,period_days,date,value,metric,total_posts,total_views,
detail_url,status,related_video_links

Detail pages exist only for hashtags currently in the Top 100 list
(URL /creative/creativeCenter/trends/hashtag/<id>?region=US&period=7|30).
Rows with no date/value (status=not found) are ignored. Values are a
relative popularity index 0-100, independently normalized inside each
period window — a 7-day 100 and a 30-day 100 are not the same absolute
volume. Zero values are kept as recorded points but treated as gaps for
line-drawing and excluded from peak / 回落 math.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


def _to_float(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _norm_tag(tag: str) -> str:
    return (tag or "").strip().lstrip("#").lower()


def parse_trend_date(s: str) -> str:
    """Return YYYY-MM-DD or ''."""
    from datetime import datetime
    s = (s or "").strip()
    if not s:
        return ""
    s = s[:10] if len(s) >= 10 and s[4] == "-" else s
    for fmt in ("%Y-%m-%d", "%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


@dataclass
class CCTrendPoint:
    date: str
    value: float
    period_days: int
    region: str = ""


@dataclass
class CCHashtagTrend:
    hashtag: str
    series: list = field(default_factory=list)
    position: str = ""
    metric: str = "Popularity index (relative 0-100)"
    totals: dict = field(default_factory=dict)
    tag_url: str = ""
    detail_urls: dict = field(default_factory=dict)
    regions: dict = field(default_factory=dict)  # period_days -> region

    def points(self, period_days: int) -> list:
        return sorted(
            [p for p in self.series if p.period_days == int(period_days)],
            key=lambda p: p.date,
        )

    def has_series(self) -> bool:
        return bool(self.series)


def _window_stats(pts: list[CCTrendPoint]):
    usable = [p for p in pts if p.value > 0]
    if not usable:
        return None
    peak = max(usable, key=lambda p: p.value)
    last = usable[-1]  # zeros are gaps; do not use a 0 last-point in 回落 math
    drop = None
    if peak.value > 0:
        drop = (peak.value - last.value) / peak.value * 100
    return {
        "n": len(pts),
        "usable": len(usable),
        "first": usable[0],
        "last": last,
        "peak": peak,
        "drop_pct": drop,
        "start": pts[0].date,
        "end": pts[-1].date,
    }


def _fmt_md(d: str) -> str:
    parts = d.split("-")
    if len(parts) == 3:
        return f"{int(parts[1])}/{int(parts[2])}"
    return d


def classify_position(tr: CCHashtagTrend) -> str:
    s30 = _window_stats(tr.points(30))
    s7 = _window_stats(tr.points(7))
    bits = []
    if s30 and s30["drop_pct"] is not None:
        drop = s30["drop_pct"]
        last, peak = s30["last"], s30["peak"]
        if last.date == peak.date or drop <= 1:
            label = "峰值"
        elif drop <= 8:
            label = f"接近峰值，回落 {drop:.1f}% from peak"
        elif last.value < peak.value:
            label = f"回落 {drop:.1f}% from peak"
        else:
            label = "上升中"
        bits.append(
            f"{label}（30日人气指数，峰值 {_fmt_md(peak.date)} 的 {peak.value:g} "
            f"→ {_fmt_md(last.date)} 的 {last.value:g}）"
        )
        if tr.regions.get(30):
            bits[-1] = bits[-1][:-1] + f"，地区 {tr.regions[30]}）"
    if s7 and s7["drop_pct"] is not None:
        last, peak = s7["last"], s7["peak"]
        bits.append(
            f"7日窗口峰值在 {_fmt_md(peak.date)}（{peak.value:g}），"
            f"{_fmt_md(last.date)} 为 {last.value:g}，"
            f"回落 {s7['drop_pct']:.1f}%"
        )
    if s30 and s7:
        bits.append("两套指数各自归一化到 0–100，不能直接横比")
    end = (s30 or s7 or {}).get("end")
    if end:
        bits.append(f"曲线最后一天是 {_fmt_md(end)}，不是报告日")
    return "。".join(bits) + "。" if bits else ""


def load_cc_trends(path) -> dict[str, CCHashtagTrend]:
    path = Path(path)
    grouped: dict[str, CCHashtagTrend] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            tag = _norm_tag(row.get("hashtag") or "")
            if not tag:
                continue
            tr = grouped.get(tag)
            if tr is None:
                tr = CCHashtagTrend(hashtag=tag)
                grouped[tag] = tr
            status = (row.get("status") or "").strip().lower()
            tag_url = (row.get("related_video_links") or "").strip()
            detail = (row.get("detail_url") or "").strip()
            period_raw = (row.get("period_days") or "").strip()
            if tag_url and not tr.tag_url:
                tr.tag_url = tag_url.split()[0]
            if detail and period_raw.isdigit():
                tr.detail_urls[int(period_raw)] = detail
            elif detail and 30 not in tr.detail_urls:
                tr.detail_urls[0] = detail
            posts = (row.get("total_posts") or "").strip()
            views = (row.get("total_views") or "").strip()
            if period_raw.isdigit() and (posts or views):
                tr.totals[int(period_raw)] = {"posts": posts, "views": views}
            metric = (row.get("metric") or "").strip()
            if metric:
                tr.metric = metric
            val = _to_float(row.get("value"))
            date = parse_trend_date(row.get("date") or "")
            if val is None or not date or not period_raw.isdigit():
                continue
            if status == "not found":
                continue
            region = (row.get("region") or "").strip()
            if not region:
                import re
                m = re.search(r"[?&]region=([A-Z]{2})", detail or "")
                region = m.group(1) if m else "US"
            tr.regions[int(period_raw)] = region
            tr.series.append(CCTrendPoint(date=date, value=val, period_days=int(period_raw), region=region))
    for tr in grouped.values():
        # drop duplicate (date, period) pairs, keep first
        seen = set()
        uniq = []
        for p in sorted(tr.series, key=lambda x: (x.period_days, x.date)):
            key = (p.period_days, p.date, p.region)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(p)
        tr.series = uniq
        tr.position = classify_position(tr)
    return grouped
