"""`data/tracker.csv`: one row per meme per report date."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .csvio import read_dicts, write_rows

COLUMNS = [
    "date", "meme_id", "name", "part", "verdict", "suggested_verdict", "total",
    "heat", "trend", "share", "competition", "window",
    "primary_metric", "primary_value", "primary_date",
    "share_median", "share_n", "ignite_date", "days_hot", "peak_status", "cc_regions",
]


def load(path: Path) -> list[dict]:
    return read_dicts(path)


def replace_day(path: Path, day: date, rows: list[dict]) -> list[dict]:
    """Replace every row of `day` with `rows` (a rebuild never leaves stale rows)."""
    keep = [r for r in load(path) if r["date"] != day.isoformat()]
    allrows = sorted(keep + rows, key=lambda r: (r["date"], r["meme_id"]))
    write_rows(path, COLUMNS, allrows)
    return allrows


def previous(rows: list[dict], meme_id: str, day: date) -> dict | None:
    earlier = [r for r in rows if r["meme_id"] == meme_id and r["date"] < day.isoformat()]
    return max(earlier, key=lambda r: r["date"]) if earlier else None


def report_dates(rows: list[dict]) -> list[str]:
    return sorted({r["date"] for r in rows})
