#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append or upsert one report day's meme pack into meme_daily_tracker.csv.

Does not invent values. Missing optional files just leave the corresponding fields blank.

Example:
  python scripts/update_tracker.py \
      --pack reports/2026-11/2026-11-10-meme-pack.json \
      --heat reports/2026-11/2026-11-10-heat.csv \
      --remix reports/2026-11/2026-11-10-remix-stats.csv \
      --cc reports/2026-11/2026-11-10-cc-hashtag-trends.csv \
      --cc-ranks reports/2026-11/2026-11-10-cc-top100-us.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as a script from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker_lib as lib  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Append a day's meme pack to the daily tracker.")
    p.add_argument("--pack", required=True, help="meme_pack_YYYY-MM-DD.json")
    p.add_argument("--heat", help="heat_YYYY-MM-DD.csv (optional)")
    p.add_argument("--remix", help="remix_stats_YYYY-MM-DD.csv (optional)")
    p.add_argument("--cc", help="cc_hashtag_trends_YYYY-MM-DD.csv (optional)")
    p.add_argument("--cc-ranks", dest="cc_ranks", help="Creative Center top list CSV (optional)")
    p.add_argument("--out", default=str(lib.DEFAULT_TRACKER), help="tracker CSV path")
    p.add_argument("--notes", default="", help="optional note written on the new rows")
    args = p.parse_args()

    pack = json.loads(Path(args.pack).read_text(encoding="utf-8"))
    report_date = pack.get("report_date")
    if not report_date:
        print("pack missing report_date", file=sys.stderr)
        return 2
    memes = pack.get("memes") or []
    if not memes:
        print("pack has no memes", file=sys.stderr)
        return 2

    heat_by = lib.index_heat(lib.read_csv(args.heat)) if args.heat else {}
    remix_med = lib.remix_medians(lib.read_csv(args.remix)) if args.remix else {}
    cc_rows = lib.read_csv(args.cc) if args.cc else []
    rank_rows = lib.read_csv(args.cc_ranks) if args.cc_ranks else []

    notes = args.notes or f"由 update_tracker.py 从 {Path(args.pack).name} 写入。"
    new_rows = [
        lib.build_row(m, report_date, heat_by, remix_med, cc_rows, rank_rows, notes)
        for m in memes
    ]

    out = Path(args.out)
    existing = lib.read_csv(out) if out.exists() else []
    merged = lib.upsert_rows(existing, new_rows)
    lib.write_csv(out, lib.TRACKER_FIELDS, merged)
    print(f"wrote {out}  total_rows={len(merged)}  upserted={len(new_rows)}  date={report_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
