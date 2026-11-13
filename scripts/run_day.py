#!/usr/bin/env python3
"""Run the code stages of a report day with resume and a timing log.

    uv run python scripts/run_day.py run  YYYY-MM-DD [--force] [--lark]
    uv run python scripts/run_day.py mark YYYY-MM-DD STAGE start|done|failed [--note TEXT]
    uv run python scripts/run_day.py status YYYY-MM-DD

`run` does check -> ingest -> scaffold -> build (-> export-lark with --lark) and resumes:
  * raw snapshots: lists which data/raw/D files already exist (collection is the agent's job; reuse them)
  * scaffold: skipped when reports/D/judgments.json already exists (rerunning would add TODO drafts)
  * build: skipped when meme-pack.json is newer than every raw file, judgments.json and data/memes.csv
  --force reruns build even when fresh; --rescaffold reruns scaffold on an existing judgments.json
  (refreshes facts, but adds TODO drafts for new candidates that must be judged or removed before build).
`mark` records agent stages (cc-lists, cc-details, watchlist, heat, remixes, judgments, chat, git-push,
wiki, base-sync) so an interrupted run shows its last completed work.
Every event is appended to reports/D/run-timing.json (Asia/Shanghai times, git commit).
"""
from __future__ import annotations

import argparse, json, subprocess, sys, time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")
RAW = ("cc-top100.csv", "cc-curves.csv", "cc-audience.csv", "heat.csv", "remixes.csv",
       "watchlist-posts.csv", "gaps.json")


def now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def commit() -> str:
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip()


def log_path(day: str) -> Path:
    return ROOT / "reports" / day / "run-timing.json"


def log(day: str, **event) -> None:
    p = log_path(day)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"date": day, "events": []}
    data["events"].append({"at": now(), "commit": commit(), **event})
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def radar(*args: str) -> int:
    return subprocess.call([sys.executable, "-m", "radar.cli", *args], cwd=ROOT)


def stage(day: str, name: str, fn) -> bool:
    t0 = time.monotonic()
    log(day, stage=name, event="start")
    rc = fn()
    secs = round(time.monotonic() - t0, 2)
    log(day, stage=name, event="done" if rc == 0 else "failed", seconds=secs, rc=rc)
    print(f"[{name}] rc={rc} {secs}s")
    return rc == 0


def build_is_fresh(day: str) -> bool:
    pack = ROOT / "reports" / day / "meme-pack.json"
    if not pack.is_file():
        return False
    deps = [ROOT / "data" / "raw" / day / f for f in RAW] + [ROOT / "reports" / day / "judgments.json",
                                                             ROOT / "data" / "memes.csv"]
    newest = max((p.stat().st_mtime for p in deps if p.is_file()), default=0)
    return pack.stat().st_mtime >= newest


def status(day: str) -> list[str]:
    raw = ROOT / "data" / "raw" / day
    have = [f for f in RAW if (raw / f).is_file()]
    missing = [f for f in RAW if f not in have]
    print(f"raw snapshots present: {', '.join(have) or '-'}")
    print(f"raw snapshots missing: {', '.join(missing) or '-'}")
    p = log_path(day)
    if p.is_file():
        last: dict[str, dict] = {}
        for e in json.loads(p.read_text(encoding="utf-8"))["events"]:
            if "stage" in e:
                last[e["stage"]] = e
        for s, e in last.items():
            print(f"  {s:12} {e['event']:8} {e['at']} {e.get('note', '')}")
    return missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("day"); r.add_argument("--force", action="store_true")
    r.add_argument("--rescaffold", action="store_true")
    r.add_argument("--lark", action="store_true", help="also write Lark batch files (export-lark)")
    m = sub.add_parser("mark"); m.add_argument("day"); m.add_argument("stage")
    m.add_argument("event", choices=["start", "done", "failed"]); m.add_argument("--note", default="")
    s = sub.add_parser("status"); s.add_argument("day")
    a = ap.parse_args()
    day = date.fromisoformat(a.day).isoformat()
    if a.cmd == "mark":
        log(day, stage=a.stage, event=a.event, note=a.note)
        return 0
    if a.cmd == "status":
        status(day)
        return 0
    missing = status(day)
    log(day, stage="raw-snapshots", event="checked", note="missing: " + ", ".join(missing) if missing else "all present")
    if not stage(day, "check", lambda: radar("check")):
        return 1
    if not stage(day, "ingest", lambda: radar("ingest", day)):
        return 1
    if (ROOT / "reports" / day / "judgments.json").is_file() and not a.rescaffold:
        log(day, stage="scaffold", event="skipped", note="judgments.json exists")
        print("[scaffold] skipped: judgments.json exists")
    elif not stage(day, "scaffold", lambda: radar("scaffold", day)):
        return 1
    if build_is_fresh(day) and not a.force:
        log(day, stage="build", event="skipped", note="meme-pack.json is newer than its inputs")
        print("[build] skipped: up to date")
    elif not stage(day, "build", lambda: radar("build", day)):
        return 1
    if a.lark and not stage(day, "export-lark", lambda: radar("export-lark", day)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
