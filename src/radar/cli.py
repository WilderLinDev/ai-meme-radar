"""`radar` command line. Run `radar --help` for the daily order."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .config import Layout, load_settings
from .csvio import DataError

DAILY = """daily order:
  radar check                 preflight
  (agent collects into data/raw/YYYY-MM-DD/)
  radar ingest  YYYY-MM-DD    validate raw files and meme ids
  radar scaffold YYYY-MM-DD   write or refresh reports/YYYY-MM-DD/judgments.json with facts
  (agent fills judgments.json)
  radar build   YYYY-MM-DD    pack, tracker, backtest, Markdown, Word, charts
  git commit and push
  radar export-lark YYYY-MM-DD  only when lark.enabled
"""


def _day(s: str) -> date:
    return date.fromisoformat(s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="radar", description=__doc__, epilog=DAILY,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path.cwd(), help="repo root (default: current folder)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="preflight: Present / Ask / Skipped")
    for name, help_ in (("ingest", "validate raw snapshots"), ("scaffold", "write the judgments draft"),
                        ("build", "build pack, tracker, backtest and reports")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("day", type=_day)
    p = sub.add_parser("export-lark", help="write Lark Base batches under data/lark-batches/")
    p.add_argument("day", type=_day)
    p.add_argument("--existing-keys", type=Path, help='JSON {table_key: [key, ...] | {key: record_id}}')
    p = sub.add_parser("schema", help="print the columns of raw files and judgments.json")
    p.add_argument("kind", nargs="?", help="a raw file name such as heat.csv, or judgments")
    args = ap.parse_args(argv)

    settings = load_settings()
    layout = Layout.from_settings(args.root.resolve(), settings)
    try:
        return _run(args, layout, settings)
    except DataError as e:
        print(f"radar {args.cmd}: {len(e.problems)} problem(s)", file=sys.stderr)
        for p in e.problems:
            print("  - " + p, file=sys.stderr)
        return 1


def _run(args, layout: Layout, settings) -> int:
    from . import pipeline

    if args.cmd == "check":
        from .check import report
        print(report(layout, settings))
    elif args.cmd == "ingest":
        raw, _ = pipeline.ingest(layout, args.day)
        for attr in ("cc_top100", "cc_curves", "cc_audience", "heat", "remixes", "watchlist_posts", "gaps"):
            print(f"{attr:16} {len(getattr(raw, attr))}")
        if raw.missing_files:
            print("missing files: " + ", ".join(raw.missing_files) + " (recorded as gaps)")
    elif args.cmd == "scaffold":
        print(pipeline.write_scaffold(layout, args.day))
    elif args.cmd == "build":
        result = pipeline.build(layout, settings, args.day)
        for p in result.outputs:
            print(p.relative_to(layout.root) if p.is_relative_to(layout.root) else p)
        if result.pack.backtest:
            print(result.pack.backtest.text_zh())
    elif args.cmd == "export-lark":
        from .export.lark import export
        for p in export(layout, settings, args.day, args.existing_keys):
            print(p.relative_to(layout.root) if p.is_relative_to(layout.root) else p)
    elif args.cmd == "schema":
        _schema(args.kind)
    return 0


def _schema(kind: str | None) -> None:
    from .judgments import Judgments
    from .raw.schemas import RAW_FILES, Gap
    from .registry import Meme

    models = {**RAW_FILES, "gaps.json": Gap, "memes.csv": Meme, "judgments": Judgments}
    for name, model in models.items():
        if kind and kind != name:
            continue
        if name == "judgments":
            print(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2))
            continue
        cols = [f"{n}{'' if f.is_required() else '?'}" for n, f in model.model_fields.items()]
        print(f"{name}: {', '.join(cols)}")
        if model.__doc__ and kind:
            print("  " + model.__doc__.strip())


if __name__ == "__main__":
    sys.exit(main())
