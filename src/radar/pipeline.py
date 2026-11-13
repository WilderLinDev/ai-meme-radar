"""The daily workflow as resumable stages. scripts/run_day.py is the only entry point.

    preflight -> sync -> discover -> research* -> scaffold -> decide* -> backtest -> report -> publish

`preflight` is a strict gate (radar.preflight): every invocation rechecks every prerequisite
(local, Ge Fei, Lark, and the agent's browser report) and, unless all pass, stops with exit code 4
before any other stage starts. There is no degraded mode: a failure in sync or publish fails the run.
Stages marked * wait for an agent file in work/DAY/ (research.json, assessments.json). A run stops
there with exit code 2 and says what to write; the next run picks up where it stopped (finished
stages are idempotent and skip their work). Every stage start / end is logged to `run_events`.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import contextmanager
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from . import backtest, db, decisions, lark, preflight as gate
from .config import REPO, Paths, Settings, now_iso, today
from .gefei.client import Client, Transport, urllib_transport
from .gefei.sync import SERVICES, Syncer, credits_spent, pending_units
from .reports import daily, deep
from .research.discover import discover
from .research.ingest import InputError, ingest_research, record_gap

DONE, WAITING, FAILED, BUSY, NOT_READY = 0, 2, 1, 3, 4


@dataclass
class Context:
    day: date
    settings: Settings
    paths: Paths
    conn: sqlite3.Connection
    transport: Transport = urllib_transport
    lark_runner: lark.Runner = lark.subprocess_runner
    resync: bool = False
    services: tuple[str, ...] = SERVICES
    say: Callable[[str], None] = print
    which: Callable[[str], str | None] = shutil.which

    @property
    def work(self) -> Path:
        return self.paths.work(self.day)


class Wait(Exception):
    pass


class NotReady(Exception):
    def __init__(self, report: gate.Report):
        super().__init__(f"{len(report.failed)} of {len(report.checks)} checks failed: "
                         + ", ".join(c.name for c in report.failed))
        self.report = report


def commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def log(conn: sqlite3.Connection, day: date, stage: str, event: str, seconds: float | None = None,
        note: str = "") -> None:
    db.insert(conn, "run_events", {"day": day.isoformat(), "stage": stage, "event": event, "at": now_iso(),
                                   "seconds": seconds, "commit_sha": commit(), "note": note[:2000]})


def last_event(conn: sqlite3.Connection, day: date, stage: str) -> dict | None:
    return db.one(conn, "SELECT * FROM run_events WHERE day=? AND stage=? ORDER BY id DESC LIMIT 1",
                  (day.isoformat(), stage))


# ---- stages ----
def preflight(ctx: Context) -> str:
    rep = gate.run_checks(ctx)
    try:
        (ctx.work / gate.REPORT_FILE).write_text(json.dumps(rep.to_json(), ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
    except OSError as e:  # an unwritable work folder is itself a failed check in the report
        ctx.say(f"(could not save {gate.REPORT_FILE}: {e.strerror or e})")
    ctx.say(rep.render())
    if not rep.ready:
        raise NotReady(rep)
    return f"READY: {len(rep.checks)} checks passed"


def sync(ctx: Context) -> str:
    done_today = db.one(ctx.conn, "SELECT 1 FROM run_events WHERE day=? AND stage='sync' AND event='done'",
                        (ctx.day.isoformat(),))
    if done_today and not ctx.resync and not pending_units(ctx.conn):
        return "skipped: already synced today (use --resync to pull again)"
    client = Client(ctx.conn, ctx.settings.token, ctx.settings.gefei.base_url, ctx.transport, ctx.day)
    rep = Syncer(ctx.conn, client, ctx.settings).run(ctx.services)  # a fatal API error fails the run
    for item in rep.locked:
        record_gap(ctx.conn, ctx.day, "哥飞数据服务", f"未解锁或不存在：{item}")
    if rep.failed:  # no partial data: stop here; the next run retries only the failed units
        raise RuntimeError(f"{len(rep.failed)} sync units failed (retried next run): {rep.failed[:3]}")
    new = ", ".join(f"{k} {len(v)}" for k, v in rep.new_batches.items()) or "none"
    return f"fetched {rep.fetched} skipped {rep.skipped} failed {len(rep.failed)} locked {len(rep.locked)} new {new}"


def discover_stage(ctx: Context) -> str:
    s = discover(ctx.conn, ctx.day, ctx.work / "candidates.json")
    return f"{ctx.work / 'candidates.json'}: {s}"


def research(ctx: Context) -> str:
    path = ctx.work / "research.json"
    if not path.is_file():
        raise Wait(f"write {path} (trends, formats, opportunities, links, evidence, gaps); "
                   f"start from {ctx.work / 'candidates.json'} and the social sweep")
    return str(ingest_research(ctx.conn, path, ctx.day))


def scaffold(ctx: Context) -> str:
    out = ctx.work / "assessments.draft.json"
    n = decisions.scaffold(ctx.conn, ctx.day, out)
    return f"{n} drafts in {out}"


def decide(ctx: Context) -> str:
    fb = decisions.ingest_feedback(ctx.conn, ctx.paths.feedback_inbox, ctx.day)
    path = ctx.work / "assessments.json"
    if not path.is_file():
        raise Wait(f"copy {ctx.work / 'assessments.draft.json'} to {path}, fill every TODO, delete what you do not "
                   f"judge today, then rerun")
    st = decisions.ingest_assessments(ctx.conn, path, ctx.day)
    return f"assessments {st}, feedback {fb}"


def backtest_stage(ctx: Context) -> str:
    return str(backtest.evaluate(ctx.conn, today()))  # stored results reflect everything known now


def report(ctx: Context) -> str:
    changed = daily.build(ctx.conn, ctx.day, ctx.paths)
    deeps = deep.build(ctx.conn, ctx.day, ctx.paths)
    return f"daily {'written' if changed else 'unchanged'} {ctx.paths.daily_report(ctx.day)}; deep {deeps}"


def publish(ctx: Context) -> str:
    res = lark.publish(ctx.conn, ctx.settings.lark, ctx.lark_runner)
    if res.failed:  # delivery is required: the run fails, and the next run retries only these documents
        raise RuntimeError(f"Lark publish failed for {len(res.failed)} documents: {res.failed[:3]}")
    return f"created {res.created} updated {res.updated} failed {res.failed}"


STAGES: list[tuple[str, Callable[[Context], str]]] = [
    ("preflight", preflight), ("sync", sync), ("discover", discover_stage), ("research", research),
    ("scaffold", scaffold), ("decide", decide), ("backtest", backtest_stage), ("report", report),
    ("publish", publish)]


class Busy(RuntimeError):
    pass


@contextmanager
def run_lock(path: Path):
    """One daily run at a time per data folder.

    An exclusive, non-blocking flock on <data>/run.lock. The kernel drops it when the process exits,
    even on a crash or kill, so a leftover file is never a stale lock. Read-only commands
    (status, tools, call) do not take it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.seek(0)
            raise Busy(f"another run holds {path} ({f.read().strip() or 'unknown holder'})") from None
        f.seek(0)
        f.truncate()
        f.write(f"pid {os.getpid()} since {now_iso()}\n")
        f.flush()
        yield
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()


def run(ctx: Context) -> int:
    ctx.paths.ensure()
    say = ctx.say
    ctx.say = lambda text: say(ctx.settings.redact(text))  # nothing printed or logged carries the token
    try:
        with run_lock(ctx.paths.lock):
            return _run(ctx)
    except Busy as e:
        ctx.say(f"[run] not started: {e}")
        return BUSY
    finally:
        ctx.say = say


def _run(ctx: Context) -> int:
    try:
        ctx.work.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # reported by the gate's folder check
    for name, fn in STAGES:
        t0 = time.monotonic()
        log(ctx.conn, ctx.day, name, "start")
        try:
            note = fn(ctx)
        except NotReady as e:
            log(ctx.conn, ctx.day, name, "failed", round(time.monotonic() - t0, 2), ctx.settings.redact(str(e)))
            return NOT_READY
        except Wait as w:
            log(ctx.conn, ctx.day, name, "waiting", round(time.monotonic() - t0, 2), ctx.settings.redact(str(w)))
            ctx.say(f"[{name}] waiting for agent: {w}")
            return WAITING
        except InputError as e:
            log(ctx.conn, ctx.day, name, "failed", round(time.monotonic() - t0, 2), ctx.settings.redact(str(e)))
            ctx.say(f"[{name}] input problems ({len(e.problems)}):\n  - " + "\n  - ".join(e.problems))
            return FAILED
        except Exception as e:  # noqa: BLE001 - every failure is logged with its stage, then surfaced
            log(ctx.conn, ctx.day, name, "failed", round(time.monotonic() - t0, 2),
                ctx.settings.redact(f"{type(e).__name__}: {e}"))
            ctx.say(f"[{name}] failed: {type(e).__name__}: {e}")
            return FAILED
        secs = round(time.monotonic() - t0, 2)
        note = ctx.settings.redact(note)
        log(ctx.conn, ctx.day, name, "skipped" if note.startswith("skipped") else "done", secs, note)
        ctx.say(f"[{name}] {secs}s {note}")
    ctx.say(f"credits spent today: {credits_spent(ctx.conn, ctx.day)}")
    return DONE


def status(conn: sqlite3.Connection, day: date, say: Callable[[str], None] = print, paths: Paths | None = None) -> None:
    for name, _ in STAGES:
        e = last_event(conn, day, name)
        if e:
            say(f"  {name:10} {e['event']:8} {e['at']} {e['note'][:160]}")
        else:
            say(f"  {name:10} -")
    units = pending_units(conn)
    if units:
        say(f"sync units to retry: {len(units)} (e.g. {units[0]['kind']}:{units[0]['item_key']}: {units[0]['last_error']})")
    pf = paths.work(day) / gate.REPORT_FILE if paths else None
    if pf and pf.is_file():
        doc = json.loads(pf.read_text(encoding="utf-8"))
        state = "READY" if doc["ready"] else f"NOT READY (failed: {', '.join(doc['failed'])})"
        say(f"preflight: {state} at {doc['checked_at']} ({pf})")
    report = db.one(conn, "SELECT path FROM reports WHERE key=?", (f"daily/{day.isoformat()}",))
    say(f"daily report: {report['path'] if report else '- (not built yet)'}")
    docs = lark.documents(conn)
    say(f"lark documents: {len(docs)}")
    for d in docs:
        line = f"  [{d['type']}] {d['name']} | {d['status']} | {d['url'] or '-'} | {d['local_path']}"
        if d["error"]:
            line += f" | error: {d['error']}"
        say(line)


def open_db(paths: Paths) -> sqlite3.Connection:
    paths.ensure()
    return db.connect(paths.db)
