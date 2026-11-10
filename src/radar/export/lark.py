"""Schema-driven Lark Base batches.

`config/lark-base.json` says, for each table, which source it reads, which
source column feeds each field, and which fields form the dedupe key. This
module only builds rows from sources and converts values by Lark field type.
The actual write goes through the user's Lark connector (no secrets here).

Lark type codes: 1 text, 2 number, 3 single select, 5 date, 7 checkbox, 15 url.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from .. import backtest as bt
from ..config import Layout, Settings
from ..csvio import DataError, read_dicts
from ..pack import Pack
from ..raw import load_day

CHUNK = 40
DETAIL_URL = "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag/{id}?region={region}&period={period}"


def _src_cc_top100(layout: Layout, settings: Settings, day: date) -> list[dict]:
    return [r.model_dump() | {"capture_date": day, "hashtag": "#" + r.hashtag,
                              "detail_url": DETAIL_URL.format(id=r.detail_id, region=r.region, period=r.period)
                              if r.detail_id else ""}
            for r in load_day(layout, day).cc_top100]


def _src_cc_curves(layout: Layout, settings: Settings, day: date) -> list[dict]:
    return [r.model_dump() | {"capture_date": day, "hashtag": "#" + r.hashtag,
                              "detail_url": DETAIL_URL.format(id=r.detail_id, region=r.region, period=r.period)
                              if r.detail_id else ""}
            for r in load_day(layout, day).cc_curves]


def _src_cc_audience(layout: Layout, settings: Settings, day: date) -> list[dict]:
    return [r.model_dump() | {"capture_date": day, "hashtag": "#" + r.hashtag} for r in load_day(layout, day).cc_audience]


def _src_tracker(layout: Layout, settings: Settings, day: date) -> list[dict]:
    return [r for r in read_dicts(layout.tracker) if r["date"] == day.isoformat()]


def _src_remixes(layout: Layout, settings: Settings, day: date) -> list[dict]:
    return [r.model_dump() | {"report_date": day, "share_rate": r.share_rate} for r in load_day(layout, day).remixes]


def _src_backtest(layout: Layout, settings: Settings, day: date) -> list[dict]:
    if not layout.backtest_json.is_file():
        return []
    evals = json.loads(layout.backtest_json.read_text(encoding="utf-8"))["evaluations"]
    for e in evals:
        e["line_zh"] = bt.Evaluation.model_validate(e).line_zh()
    return evals


def _src_watchlist(layout: Layout, settings: Settings, day: date) -> list[dict]:
    return read_dicts(layout.watchlist)


def _src_digest(layout: Layout, settings: Settings, day: date) -> list[dict]:
    pack = Pack.load(layout.pack(day))
    names = {v: "、".join(m.facts.name for m in pack.ranked() if m.judgment.verdict == v) for v in ("make", "watch", "skip")}
    return [{"date": day, "doc_url": settings.lark.digest_docs.get(day.isoformat(), ""),
             "make": names["make"], "watch": names["watch"], "skip": names["skip"],
             "note": pack.backtest.text_zh() if pack.backtest else ""}]


SOURCES: dict[str, Callable[[Layout, Settings, date], list[dict]]] = {
    "cc_top100": _src_cc_top100,
    "cc_curves": _src_cc_curves,
    "cc_audience": _src_cc_audience,
    "tracker": _src_tracker,
    "remixes": _src_remixes,
    "backtest": _src_backtest,
    "watchlist": _src_watchlist,
    "digest": _src_digest,
}


def _display(field: dict, row: dict):
    """The value before Lark type conversion: mapped, as text for selects and keys."""
    if "const" in field:
        return field["const"]
    v = row.get(field["from"])
    if v is None or v == "":
        return None
    if "map" in field:
        v = field["map"].get(str(v), v)
    return v


def _convert(ftype: int, v, tz: ZoneInfo):
    if v is None:
        return None
    if ftype == 2:
        return float(v)
    if ftype == 5:
        d = v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
        return int(datetime.combine(d, time(0), tz).timestamp() * 1000)
    if ftype == 7:
        return str(v).lower() in {"1", "true", "yes", "y"} if not isinstance(v, bool) else v
    if ftype == 15:
        return {"link": str(v), "text": str(v)}
    return v.isoformat() if isinstance(v, date) else str(v)


def build_records(table: dict, rows: list[dict], tz: ZoneInfo) -> list[tuple[str, dict]]:
    fields = {f["field_name"]: f for f in table["fields"] if "from" in f or "const" in f}
    out = []
    for row in rows:
        shown = {name: _display(f, row) for name, f in fields.items()}
        key = "|".join("" if shown.get(k) is None else (shown[k].isoformat() if isinstance(shown[k], date) else str(shown[k]))
                       for k in table["dedupe"])
        rec = {"去重键": key}
        for name, f in fields.items():
            val = _convert(f["type"], shown[name], tz)
            if val is not None:
                rec[name] = val
        out.append((key, rec))
    return out


def export(layout: Layout, settings: Settings, day: date, existing: Path | None = None) -> list[Path]:
    lark = settings.lark
    missing = [k for k in ("base_app_token", "wiki_parent_url") if not getattr(lark, k)]
    schema = json.loads(layout.lark_schema.read_text(encoding="utf-8"))
    missing += [f"tables.{t['key']}" for t in schema["tables"] if not lark.tables.get(t["key"])]
    if not lark.enabled:
        raise DataError(["Lark export is off (lark.enabled = false in settings.toml)."])
    if missing:
        raise DataError([f"Lark export needs lark.{m} in settings.toml" for m in missing])

    tz = ZoneInfo(schema["base_timezone"])
    known = json.loads(existing.read_text(encoding="utf-8")) if existing else {}
    out_dir = layout.lark_batches(day)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for table in schema["tables"]:
        records = build_records(table, SOURCES[table["source"]](layout, settings, day), tz)
        seen = known.get(table["key"], [])
        ids = seen if isinstance(seen, dict) else {k: None for k in seen}
        create = [{"fields": r} for k, r in records if k not in ids]
        update = [{"record_id": ids[k], "fields": r} for k, r in records if k in ids and ids[k]]
        for kind, recs in (("create", create), ("update", update)):
            for i in range(0, len(recs), CHUNK):
                path = out_dir / f"{table['key']}.{kind}.{i // CHUNK + 1:02d}.json"
                path.write_text(json.dumps(recs[i:i + CHUNK], ensure_ascii=False), encoding="utf-8")
                written.append(path)
    return written
