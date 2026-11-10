# -*- coding: utf-8 -*-
"""Load per-meme heat time series (CSV or JSON) and classify current position.

Input CSV columns: meme,date,metric,value,source[,complete]
Input JSON: {memes: {Name: {series: [...], position, x_query, sources}}}

complete=false marks a partial day or a same-day snapshot. Those points may be
drawn with a hollow marker but are never used for peak / 回落 math, and missing
dates are left as gaps (no interpolation).
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from reportlib.remix_lib import canonical_meme


@dataclass
class HeatPoint:
    date: str
    metric: str
    value: float
    source: str
    complete: bool = True
    rank: int | None = None


@dataclass
class MemeHeat:
    meme: str
    series: list = field(default_factory=list)
    position: str = ""
    x_query: str = ""
    x_query_note: str = ""
    sources: list = field(default_factory=list)

    def points(self, metric: str, complete_only=False) -> list[HeatPoint]:
        out = [p for p in self.series if p.metric == metric]
        if complete_only:
            out = [p for p in out if p.complete]
        return sorted(out, key=lambda p: p.date)

    def metrics(self) -> list[str]:
        seen = []
        for p in self.series:
            if p.metric not in seen:
                seen.append(p.metric)
        return seen


def _as_bool(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def _to_float(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def load_heat(path) -> dict[str, MemeHeat]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        out = {}
        for name, entry in (raw.get("memes") or raw).items():
            if not isinstance(entry, dict):
                continue
            key = canonical_meme(name) or name
            mh = MemeHeat(
                meme=key,
                position=entry.get("position") or "",
                x_query=entry.get("x_query") or "",
                x_query_note=entry.get("x_query_note") or "",
                sources=list(entry.get("sources") or []),
            )
            for rec in entry.get("series") or []:
                val = _to_float(rec.get("value"))
                if val is None or not rec.get("date"):
                    continue
                mh.series.append(HeatPoint(
                    date=str(rec["date"])[:10],
                    metric=rec.get("metric") or "value",
                    value=val,
                    source=rec.get("source") or "",
                    complete=_as_bool(rec.get("complete", True)),
                    rank=rec.get("rank"),
                ))
            out[key] = mh
        return out

    grouped = defaultdict(list)
    extra = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = canonical_meme(row.get("meme") or "") or row.get("meme")
            val = _to_float(row.get("value"))
            if not name or val is None or not row.get("date"):
                continue
            grouped[name].append(HeatPoint(
                date=str(row["date"])[:10],
                metric=row.get("metric") or "value",
                value=val,
                source=row.get("source") or "",
                complete=_as_bool(row.get("complete", True)),
            ))
    return {k: MemeHeat(meme=k, series=v) for k, v in grouped.items()}


METRIC_LABEL = {
    "x_posts": "X 每日发帖",
    "viralremix_new_videos": "ViralRemix 每日新视频",
    "remix_sample_posts": "样本二创发布条数",
    "remix_sample_views": "样本二创按发布日的播放合计",
}
