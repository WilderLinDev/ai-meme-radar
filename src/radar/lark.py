"""Publish finished Markdown reports to Lark Docs. Reports only; never data.

Local Markdown is authoritative. Each report maps to one Lark document:
* `daily/DAY`           -> one document per day
* `opportunity/<id>`    -> one document per opportunity, overwritten with its latest report
The map (document id, URL, last synced content hash) lives in `lark_docs`, so a
document is created once and later runs update it. Publishing is required:
the preflight gate verifies login, destinations and edit rights before a run
starts, and a publish failure fails the run (local reports are already
written; the next run retries only the publish, never duplicating a document).
Writes go through `lark-cli docs +create / +update` with the user's own login.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import db
from .config import LarkSettings, now_iso

Runner = Callable[[list[str], Path], tuple[int, str, str]]


def subprocess_runner(args: list[str], cwd: Path) -> tuple[int, str, str]:
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout, p.stderr


@dataclass
class PublishResult:
    created: list[str]
    updated: list[str]
    failed: list[str]


def doc_key(report: dict) -> str:
    if report["kind"] == "opportunity":
        return "opportunity/" + report["entity"].split(":", 1)[1]
    return report["key"]


def _latest_reports(conn: sqlite3.Connection) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for r in db.rows(conn, "SELECT * FROM reports ORDER BY day, key"):
        latest[doc_key(r)] = r
    return latest


def pending(conn: sqlite3.Connection) -> list[tuple[str, dict]]:
    """(doc_key, latest report) pairs whose content differs from what Lark has."""
    out = []
    for k, r in _latest_reports(conn).items():
        d = db.one(conn, "SELECT synced_hash, status FROM lark_docs WHERE doc_key=?", (k,))
        if not d or d["synced_hash"] != r["content_hash"] or d["status"] != "synced":
            out.append((k, r))
    return out


def documents(conn: sqlite3.Connection) -> list[dict]:
    """Every report's Lark document: name, type, status, URL, error, local path.

    status: synced (Lark has the latest local content), stale (published, local report changed since),
    failed (last publish failed; see error), unpublished (never published, e.g. Lark disabled).
    """
    out = []
    for k, r in _latest_reports(conn).items():
        d = db.one(conn, "SELECT * FROM lark_docs WHERE doc_key=?", (k,)) or {}
        if d.get("status") == "failed":
            status = "failed"
        elif d.get("status") == "synced":
            status = "synced" if d.get("synced_hash") == r["content_hash"] else "stale"
        else:
            status = "unpublished"
        out.append({"doc_key": k, "name": r["title"], "type": r["kind"], "status": status,
                    "url": d.get("url") or "", "error": d.get("last_error") or "", "local_path": r["path"],
                    "synced_at": d.get("synced_at") or ""})
    return out


def _parse(stdout: str) -> dict:
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    data = doc.get("data") or {}
    return data.get("document") or data


def publish(conn: sqlite3.Connection, settings: LarkSettings, runner: Runner = subprocess_runner) -> PublishResult:
    if not settings.daily_parent:
        raise RuntimeError("[lark] daily_parent is empty; publishing is required (the preflight gate checks this)")
    res = PublishResult([], [], [])
    for key, report in pending(conn):
        path = Path(report["path"])
        if not path.is_file():
            res.failed.append(f"{key}: local file missing {path}")
            continue
        d = db.one(conn, "SELECT * FROM lark_docs WHERE doc_key=?", (key,))
        parent = settings.opportunity_parent or settings.daily_parent if report["kind"] == "opportunity" \
            else settings.daily_parent
        base = [settings.cli, "docs"]
        if d and d["doc_id"]:
            args = base + ["+update", "--doc", d["doc_id"], "--command", "overwrite", "--doc-format", "markdown",
                           "--content", f"@{path.name}", "--as", settings.identity, "--format", "json"]
        else:
            args = base + ["+create", "--doc-format", "markdown", "--title", report["title"], "--content",
                           f"@{path.name}", "--parent-token", parent, "--as", settings.identity, "--format", "json"]
        code, out, err = runner(args, path.parent)
        info = _parse(out) if code == 0 else {}
        ok = code == 0 and (bool(d and d["doc_id"]) or bool(info.get("document_id")))
        with db.tx(conn):
            if ok:
                conn.execute(
                    "INSERT INTO lark_docs (doc_key, doc_id, url, synced_hash, synced_report, status, attempts,"
                    " last_error, synced_at) VALUES (?,?,?,?,?,'synced',1,NULL,?) ON CONFLICT(doc_key) DO UPDATE SET"
                    " doc_id=COALESCE(excluded.doc_id, lark_docs.doc_id), url=COALESCE(excluded.url, lark_docs.url),"
                    " synced_hash=excluded.synced_hash, synced_report=excluded.synced_report, status='synced',"
                    " attempts=lark_docs.attempts+1, last_error=NULL, synced_at=excluded.synced_at",
                    (key, info.get("document_id") or (d["doc_id"] if d else None), info.get("url") or None,
                     report["content_hash"], report["key"], now_iso()))
                (res.updated if d and d["doc_id"] else res.created).append(key)
            else:
                msg = (err or out or f"exit {code}").strip()[:500]
                conn.execute(
                    "INSERT INTO lark_docs (doc_key, status, attempts, last_error) VALUES (?,'failed',1,?)"
                    " ON CONFLICT(doc_key) DO UPDATE SET status='failed', attempts=lark_docs.attempts+1,"
                    " last_error=excluded.last_error", (key, msg))
                res.failed.append(f"{key}: {msg}")
    return res
