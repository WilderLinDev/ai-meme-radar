"""Deterministic time-series facts. The agent reads these; it never recomputes them.

A series is the ordered values of one (entity, metric, region, source) in the
evidence table, or the heat_ratio snapshots of one Ge Fei keyword. Missing
days stay missing: nothing is interpolated.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from dataclasses import asdict, dataclass

from .. import db
from ..text import parse_ref

RISE = 0.15  # +15% = rising, -15% = falling, between = holding


@dataclass
class Point:
    at: str
    value: float
    ident: dict | None = None  # what was measured: source, metric, unit, definition, region
    day: str = ""  # research day it became available (evidence.day / snapshot capture date)


def identity_key(ident: dict | None) -> str:
    """Two observations are comparable only when these keys are equal (and not empty)."""
    return db.dumps(ident) if ident else ""


@dataclass
class SeriesStats:
    label: str
    n: int
    first_at: str
    last_at: str
    latest: float
    previous: float | None
    change_pct: float | None  # latest vs previous point
    peak: float
    peak_at: str
    from_peak_pct: float | None
    direction: str  # rising / holding / falling / single

    def to_dict(self) -> dict:
        return asdict(self)


def direction_of(change: float | None) -> str:
    if change is None:
        return "single"
    if change >= RISE:
        return "rising"
    if change <= -RISE:
        return "falling"
    return "holding"


def pct(new: float, old: float) -> float | None:
    if old == 0:
        return None
    return (new - old) / abs(old)


def stats(label: str, points: list[Point]) -> SeriesStats | None:
    pts = [p for p in points if p.value is not None]
    if not pts:
        return None
    latest, prev = pts[-1], pts[-2] if len(pts) > 1 else None
    peak = max(pts, key=lambda p: p.value)
    change = pct(latest.value, prev.value) if prev else None
    return SeriesStats(
        label=label, n=len(pts), first_at=pts[0].at, last_at=latest.at, latest=latest.value,
        previous=prev.value if prev else None, change_pct=change, peak=peak.value, peak_at=peak.at,
        from_peak_pct=pct(latest.value, peak.value) if peak.value else None, direction=direction_of(change))


def evidence_series(conn: sqlite3.Connection, entity: str, metric: str, region: str = "", source: str = "",
                    until: str | None = None, ident: dict | None = None,
                    as_of_day: date | None = None) -> list[Point]:
    """One value per collection day (the last that day), ordered by time, from ONE measurement identity.

    The identity is (source, metric, unit, metric_definition, region). Without `ident`, the identity
    of the latest matching observation is used, so a series never mixes sources, units or definitions.
    """
    sql = ("SELECT collected_at, value, source, unit, metric_definition, day FROM evidence WHERE entity=? AND metric=?"
           " AND region=? AND value IS NOT NULL")
    params: list = [entity, metric, region.upper()]
    if source:
        sql += " AND source=?"
        params.append(source)
    if until:
        sql += " AND collected_at <= ?"
        params.append(until)
    if as_of_day:  # only what had been ingested by then, however it was back-dated
        sql += " AND day <= ?"
        params.append(as_of_day.isoformat())
    found = db.rows(conn, sql + " ORDER BY collected_at", params)

    def ident_of(r: dict) -> dict:
        return {"kind": "evidence", "entity": entity, "source": r["source"], "metric": metric,
                "unit": r["unit"], "definition": r["metric_definition"], "region": region.upper()}
    if not found:
        return []
    want = identity_key(ident or ident_of(found[-1]))
    by_day: dict[str, Point] = {}
    for r in found:
        i = ident_of(r)
        if identity_key(i) == want:
            by_day[r["collected_at"][:10]] = Point(r["collected_at"], float(r["value"]), i, r["day"])
    return list(by_day.values())


def keyword_heat_series(conn: sqlite3.Connection, keyword: str, until: str | None = None,
                        as_of_day: date | None = None) -> list[Point]:
    sql = "SELECT captured_at, heat_ratio FROM keyword_snapshots WHERE keyword=? AND heat_ratio IS NOT NULL"
    params: list = [keyword]
    if until:
        sql += " AND captured_at <= ?"
        params.append(until)
    if as_of_day:
        sql += " AND substr(captured_at, 1, 10) <= ?"
        params.append(as_of_day.isoformat())
    ident = {"kind": "keyword_heat", "source": "Ge Fei", "metric": "heat_ratio", "keyword": keyword,
             "unit": "x GPTs baseline", "definition": "7-day heat relative to the GPTs benchmark keyword",
             "region": ""}
    by_day: dict[str, Point] = {}
    for r in db.rows(conn, sql + " ORDER BY captured_at", params):
        by_day[r["captured_at"][:10]] = Point(r["captured_at"], float(r["heat_ratio"]), ident, r["captured_at"][:10])
    return list(by_day.values())


def tracked_points(conn: sqlite3.Connection, tracked: dict, entity: str, until: str | None = None,
                   ident: dict | None = None, as_of_day: date | None = None) -> list[Point]:
    """The tracked series; pass the frozen `ident` to keep later observations comparable to the baseline."""
    if tracked["kind"] == "keyword_heat":
        from ..text import keyword_key
        pts = keyword_heat_series(conn, keyword_key(tracked["keyword"]), until, as_of_day)
        return [p for p in pts if not ident or identity_key(p.ident) == identity_key(ident)]
    return evidence_series(conn, tracked.get("entity") or entity, tracked["metric"], tracked.get("region", ""),
                           tracked.get("source", ""), until, ident, as_of_day)


def entity_facts(conn: sqlite3.Connection, entity: str, links: dict) -> dict:
    """Everything code knows about an entity, for the scaffold and the frozen snapshot."""
    kind, ident = parse_ref(entity)
    ev = db.rows(conn, "SELECT channel, source, metric, region, value, unit, metric_definition, collected_at, tag,"
                       " confidence, day, ref"
                       " FROM evidence WHERE entity=? ORDER BY collected_at", (entity,))
    series = []
    seen = set()
    for e in ev:
        if e["value"] is None or not e["metric"]:
            continue
        key = (e["metric"], e["region"], e["source"], e["unit"], e["metric_definition"])
        if key in seen:
            continue
        seen.add(key)
        measured = {"kind": "evidence", "entity": entity, "source": e["source"], "metric": e["metric"],
                    "unit": e["unit"], "definition": e["metric_definition"], "region": e["region"]}
        s = stats(f"{e['source']} {e['metric']} {e['region'] or '-'}",
                  evidence_series(conn, entity, e["metric"], e["region"], e["source"], ident=measured))
        if s:
            series.append({"metric": e["metric"], "region": e["region"], "source": e["source"], "unit": e["unit"],
                           "definition": e["metric_definition"], **s.to_dict()})
    channels: dict[str, int] = {}
    for e in ev:
        channels[e["channel"]] = channels.get(e["channel"], 0) + 1
    linked = sorted({(d if s == entity else s, rel) for (s, d, rel) in links if entity in (s, d)})
    keywords = []
    for other, rel in linked:
        if other.startswith("keyword:"):
            kw = other.split(":", 1)[1]
            s = stats(f"Ge Fei heat_ratio {kw}", keyword_heat_series(conn, kw))
            snap = db.one(conn, "SELECT kind, growth_pct, verdict, trend_now FROM keyword_snapshots WHERE keyword=?"
                                " ORDER BY id DESC LIMIT 1", (kw,))
            keywords.append({"keyword": kw, "heat": s.to_dict() if s else None, **(snap or {})})
    ent = db.one(conn, "SELECT first_seen_day, updated_day FROM entities WHERE kind=? AND id=?", (kind, ident))
    first_ev = ev[0]["collected_at"] if ev else None
    return {
        "entity": entity,
        "first_seen_day": ent["first_seen_day"] if ent else None,
        "first_evidence_at": first_ev,
        "evidence_count": len(ev),
        "evidence_by_channel": channels,
        "evidence_days": sorted({e["day"] for e in ev}),
        "series": series,
        "keywords": keywords,
        "links": [{"entity": o, "relation": r} for o, r in linked],
    }
