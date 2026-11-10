"""A meme's primary heat series: the one series the backtest is judged on."""
from __future__ import annotations

from datetime import date

from ..raw import History
from ..registry import Meme
from .lifecycle import Point

METRIC_ZH = {
    "viralremix_new_videos": "ViralRemix 日新视频【第三方读数】",
    "x_posts": "X 日发帖【已核实】",
    "cc_index_30d": "Creative Center 30 日人气指数【第三方读数】",
    "none": "没有可回测的全站日序列",
}


def primary_points(meme: Meme, hist: History, until: date, capture: date | None = None) -> list[Point]:
    """Complete, non-gap points on or before `until`.

    For `cc_index_30d` all points come from a single capture (default: the
    latest one), because each capture re-normalises the curve to 0-100.
    Zero readings on a Creative Center curve are gaps, not real zeros.
    """
    if meme.primary_metric == "none":
        return []
    if meme.primary_metric == "cc_index_30d":
        pts = hist.curve(meme.cc_hashtags[0], meme.primary_region, 30, capture)
        return [Point(p.date, p.value) for p in pts if p.date <= until and p.value > 0]
    return [Point(p.date, p.value) for p in hist.series(meme.id, meme.primary_metric)
            if p.complete and p.date <= until]


def value_on(meme: Meme, hist: History, base_day: date, target: date) -> tuple[float, float] | None:
    """(baseline value on base_day, value on target) read from comparable data.

    Counts use the merged series. Creative Center indexes use the latest single
    capture that has complete points on both days.
    """
    if meme.primary_metric == "none":
        return None
    if meme.primary_metric == "cc_index_30d":
        for cap in hist.curve_captures(meme.cc_hashtags[0], meme.primary_region, 30):
            pts = {p.date: p.value for p in primary_points(meme, hist, target, cap)}
            if base_day in pts and target in pts:
                return pts[base_day], pts[target]
        return None
    pts = {p.date: p.value for p in primary_points(meme, hist, target)}
    if base_day in pts and target in pts:
        return pts[base_day], pts[target]
    return None
