"""Load and validate raw snapshots, one day or all days up to a date."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from ..config import Layout
from ..csvio import DataError, read_rows
from ..registry import Registry
from .schemas import (RAW_FILES, CCAudience, CCCurvePoint, CCRank, Gap, HeatPoint,
                      Remix, WatchlistPost)

__all__ = ["RawDay", "History", "load_day", "load_history", "RAW_FILES"]


@dataclass
class RawDay:
    day: date
    cc_top100: list[CCRank] = field(default_factory=list)
    cc_curves: list[CCCurvePoint] = field(default_factory=list)
    cc_audience: list[CCAudience] = field(default_factory=list)
    heat: list[HeatPoint] = field(default_factory=list)
    remixes: list[Remix] = field(default_factory=list)
    watchlist_posts: list[WatchlistPost] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)

    def meme_ids(self) -> set[str]:
        ids = {p.meme_id for p in self.heat} | {r.meme_id for r in self.remixes}
        ids |= {p.meme_id for p in self.watchlist_posts if p.meme_id}
        return ids


_ATTR = {
    "cc-top100.csv": "cc_top100",
    "cc-curves.csv": "cc_curves",
    "cc-audience.csv": "cc_audience",
    "heat.csv": "heat",
    "remixes.csv": "remixes",
    "watchlist-posts.csv": "watchlist_posts",
}


def load_day(layout: Layout, day: date, registry: Registry | None = None) -> RawDay:
    folder = layout.raw_dir(day)
    out = RawDay(day=day)
    problems: list[str] = []
    for fname, model in RAW_FILES.items():
        path = folder / fname
        if not path.is_file():
            out.missing_files.append(fname)
            continue
        try:
            setattr(out, _ATTR[fname], read_rows(path, model))
        except DataError as e:
            problems += e.problems
    gaps_path = folder / "gaps.json"
    if gaps_path.is_file():
        try:
            out.gaps = TypeAdapter(list[Gap]).validate_json(gaps_path.read_bytes())
        except ValidationError as e:
            problems += [f"gaps.json: {err['loc']}: {err['msg']}" for err in e.errors()]
    if problems:
        raise DataError(problems)
    if registry is not None:
        registry.require(out.meme_ids(), f"data/raw/{day}")
    return out


@dataclass
class History:
    """All raw snapshots captured on or before `until`, merged.

    Heat points are absolute counts, so for a given (meme, metric, date) the
    latest complete capture wins. Creative Center curves are normalised per capture
    window, so they are kept per capture and never mixed across captures.
    """
    until: date
    heat: dict[tuple[str, str], dict[date, HeatPoint]] = field(default_factory=dict)
    cc_curves: dict[date, list[CCCurvePoint]] = field(default_factory=dict)

    def series(self, meme_id: str, metric: str) -> list[HeatPoint]:
        pts = self.heat.get((meme_id, metric), {})
        return [pts[d] for d in sorted(pts)]

    def metrics_for(self, meme_id: str) -> list[str]:
        return sorted({m for (mid, m) in self.heat if mid == meme_id})

    def curve(self, hashtag: str, region: str, period: int, capture: date | None = None) -> list[CCCurvePoint]:
        """Curve points from one capture (default: the latest capture that has this curve)."""
        captures = [capture] if capture else sorted(self.cc_curves, reverse=True)
        for cap in captures:
            pts = [p for p in self.cc_curves.get(cap, [])
                   if p.hashtag == hashtag and p.region == region and p.period == period]
            if pts:
                return sorted(pts, key=lambda p: p.date)
        return []

    def curve_captures(self, hashtag: str, region: str, period: int) -> list[date]:
        return sorted((cap for cap, pts in self.cc_curves.items()
                       if any(p.hashtag == hashtag and p.region == region and p.period == period for p in pts)),
                      reverse=True)


def load_history(layout: Layout, until: date) -> History:
    hist = History(until=until)
    for day in layout.raw_days():
        if day > until:
            continue
        folder = layout.raw_dir(day)
        if (folder / "heat.csv").is_file():
            for p in read_rows(folder / "heat.csv", HeatPoint):
                slot = hist.heat.setdefault((p.meme_id, p.metric), {})
                prev = slot.get(p.date)
                # a later capture wins, except that a partial point never replaces a complete one
                if prev is None or p.complete or not prev.complete:
                    slot[p.date] = p
        if (folder / "cc-curves.csv").is_file():
            hist.cc_curves[day] = read_rows(folder / "cc-curves.csv", CCCurvePoint)
    return hist


def write_gaps(path: Path, gaps: list[Gap]) -> None:
    path.write_text(json.dumps([g.model_dump() for g in gaps], ensure_ascii=False, indent=2), encoding="utf-8")
