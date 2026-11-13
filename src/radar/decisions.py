"""Assessments (agent), feedback (human), and the effective state of every entity.

Assessments are immutable revisions: re-ingesting a changed file for the same
day adds revision N+1, never edits N. Feedback is append-only too. The
effective state of an entity on a day is its latest assessment up to that day
with any later human feedback applied on top, and it always says which parts
came from whom.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import db
from .config import TZ, now_iso
from .research import metrics
from .research.ingest import InputError, add_link_event, current_links, entity_exists, load_model
from .research.models import (DEEP_SECTIONS, DEFAULT_DIRECTION, DIMENSIONS, AssessmentFile, FeedbackFile,
                               check_link, split_link_value)
from .text import ASSESSABLE, keyword_key, parse_ref, ref

KEY_DECISIONS = ("build", "validate")
KEY_PRIORITIES = ("P0", "P1")


def is_key(state: dict) -> bool:
    return state["entity"].startswith("opportunity:") and (
        state["decision"] in KEY_DECISIONS or state["priority"] in KEY_PRIORITIES)


def _end_of(day: date) -> str:
    return datetime.combine(day, time(23, 59, 59), TZ).isoformat()


def latest_assessment(conn: sqlite3.Connection, entity: str, as_of: date | None = None) -> dict | None:
    sql = "SELECT * FROM assessments WHERE entity=?"
    params: list = [entity]
    if as_of:
        sql += " AND day <= ?"
        params.append(as_of.isoformat())
    r = db.one(conn, sql + " ORDER BY day DESC, revision DESC LIMIT 1", params)
    if r:
        r["body"] = json.loads(r["body_json"])
        r["snapshot"] = json.loads(r["snapshot_json"])
    return r


def effective(conn: sqlite3.Connection, entity: str, as_of: date | None = None) -> dict | None:
    a = latest_assessment(conn, entity, as_of)
    if not a:
        return None
    state = {"entity": entity, "assessment_id": a["id"], "assessed_day": a["day"], "revision": a["revision"],
             "lifecycle": a["lifecycle"], "decision": a["decision"], "priority": a["priority"],
             "confidence": a["confidence"], "body": a["body"], "overrides": [], "directions": []}
    sql = "SELECT * FROM feedback WHERE entity=? AND at > ?"
    params: list = [entity, a["created_at"]]
    if as_of:
        sql += " AND at <= ?"
        params.append(_end_of(as_of))
    for f in db.rows(conn, sql + " ORDER BY at, id", params):
        if f["field"] in ("decision", "priority", "lifecycle"):
            state["overrides"].append({"field": f["field"], "from": state[f["field"]], "to": f["new_value"],
                                       "reason": f["reason"], "author": f["author"], "at": f["at"]})
            state[f["field"]] = f["new_value"]
        elif f["field"] == "direction":
            state["directions"].append({"note": f["new_value"], "reason": f["reason"], "author": f["author"],
                                        "at": f["at"]})
    return state


def assessed_entities(conn: sqlite3.Connection, as_of: date | None = None) -> list[str]:
    sql = "SELECT DISTINCT entity FROM assessments"
    params: list = []
    if as_of:
        sql += " WHERE day <= ?"
        params.append(as_of.isoformat())
    return [r["entity"] for r in db.rows(conn, sql + " ORDER BY entity", params)]


def all_effective(conn: sqlite3.Connection, as_of: date) -> list[dict]:
    return [s for s in (effective(conn, e, as_of) for e in assessed_entities(conn, as_of)) if s]


# ---- scaffold ----
def scaffold(conn: sqlite3.Connection, day: date, out: Path) -> int:
    """Write assessments.draft.json: every entity worth judging today, with facts and the last judgment."""
    links = current_links(conn)
    todo: list[str] = []
    for e in db.rows(conn, "SELECT kind, id, first_seen_day FROM entities WHERE kind IN (?,?) ORDER BY kind, id",
                     ASSESSABLE):
        r = ref(e["kind"], e["id"])
        state = effective(conn, r, day)
        new_ev = db.one(conn, "SELECT 1 FROM evidence WHERE entity=? AND day=?", (r, day.isoformat()))
        if state is None or new_ev or e["first_seen_day"] == day.isoformat() or is_key(state):
            todo.append(r)
    drafts = []
    for r in todo:
        facts = metrics.entity_facts(conn, r, links)
        st = effective(conn, r, day)
        if st and (st["overrides"] or st["directions"]):
            facts["human_feedback"] = {"overrides": st["overrides"], "directions": st["directions"]}
        prev = latest_assessment(conn, r, day)
        if prev:
            body = {k: v for k, v in prev["body"].items() if k not in ("facts", "carried_from")}
            drafts.append({"entity": r, "carried_from": prev["day"], **body, "facts": facts})
        else:
            drafts.append({
                "entity": r, "lifecycle": "TODO early_signal|emerging|proven|fading",
                "decision": "TODO build|validate|monitor|skip", "priority": "TODO P0-P3",
                "confidence": "TODO high|medium|low",
                "dimensions": {d: {"level": "TODO high|medium|low|unknown", "note": "", "evidence": []}
                               for d in DIMENSIONS},
                "summary": "", "rationale": "", "why_now": "", "assumptions": [], "open_questions": [],
                "next_steps": [], "expected_direction": None, "tracked": None,
                "deep": {s: "" for s in DEEP_SECTIONS} if r.startswith("opportunity:") else {},
                "facts": facts})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"day": day.isoformat(), "assessments": drafts, "notes": ""},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(drafts)


# ---- ingest ----
def _evidence_ref_ok(conn: sqlite3.Connection, r: str) -> bool:
    if r.startswith("call:"):
        try:
            return db.one(conn, "SELECT 1 FROM api_calls WHERE id=? AND ok=1", (int(r[5:]),)) is not None
        except ValueError:
            return False
    return db.one(conn, "SELECT 1 FROM evidence WHERE ref=?", (r,)) is not None


def ingest_assessments(conn: sqlite3.Connection, path: Path, day: date) -> dict:
    af: AssessmentFile = load_model(path, AssessmentFile)
    problems: list[str] = []
    if af.day != day:
        problems.append(f"{path.name}: day is {af.day}, expected {day}")
    links = current_links(conn)
    for a in af.assessments:
        ent = ref(*parse_ref(a.entity))
        if not entity_exists(conn, ent):
            problems.append(f"{ent}: not defined; add it to research.json first")
            continue
        for dim, d in a.dimensions.items():
            for r in d.evidence:
                if not _evidence_ref_ok(conn, r):
                    problems.append(f"{ent}.{dim}: evidence {r!r} not found (use an evidence ref or call:<id>)")
            if not d.note.strip():
                problems.append(f"{ent}.{dim}: note is empty; say what the level rests on, or why unknown")
        if a.tracked:
            pts = metrics.tracked_points(conn, a.tracked.model_dump(), ent)
            if a.tracked.kind == "keyword_heat" and not db.one(conn, "SELECT 1 FROM keywords WHERE keyword=?",
                                                               (keyword_key(a.tracked.keyword),)):
                problems.append(f"{ent}: tracked keyword {a.tracked.keyword!r} is not in the Ge Fei keyword store")
            elif not pts:
                problems.append(f"{ent}: tracked series has no data yet; pick one with at least one value")
        if not a.summary.strip() or not a.rationale.strip():
            problems.append(f"{ent}: summary and rationale are required")
        state = {"entity": ent, "decision": a.decision, "priority": a.priority}
        if is_key(state):
            empty = [s for s in DEEP_SECTIONS if not a.deep.get(s, "").strip()]
            if empty:
                problems.append(f"{ent}: key opportunity ({a.decision}/{a.priority}) needs deep sections {empty}")
        if a.decision in KEY_DECISIONS and not a.next_steps:
            problems.append(f"{ent}: {a.decision} needs next_steps")
    if problems:
        raise InputError(problems)

    stats = {"new": 0, "unchanged": 0}
    with db.tx(conn):
        for a in af.assessments:
            ent = ref(*parse_ref(a.entity))
            body = a.model_dump(exclude={"facts", "carried_from", "entity"}, mode="json")
            body["expected_direction"] = a.expected_direction or DEFAULT_DIRECTION[a.lifecycle]
            h = db.sha(body)
            last = db.one(conn, "SELECT revision, content_hash FROM assessments WHERE day=? AND entity=?"
                                " ORDER BY revision DESC LIMIT 1", (day.isoformat(), ent))
            if last and last["content_hash"] == h:
                stats["unchanged"] += 1
                continue
            facts = metrics.entity_facts(conn, ent, links)
            baseline = None
            if a.tracked:
                pts = metrics.tracked_points(conn, a.tracked.model_dump(), ent, until=now_iso())
                if pts:
                    baseline = {"at": pts[-1].at, "value": pts[-1].value, "ident": pts[-1].ident}
            snapshot = {"facts": facts, "tracked": a.tracked.model_dump() if a.tracked else None,
                        "baseline": baseline, "frozen_at": now_iso(), "notes": af.notes}
            db.insert(conn, "assessments", {
                "day": day.isoformat(), "entity": ent, "revision": (last["revision"] + 1) if last else 1,
                "author": "agent", "lifecycle": a.lifecycle, "decision": a.decision, "priority": a.priority,
                "confidence": a.confidence, "body_json": db.dumps(body), "snapshot_json": db.dumps(snapshot),
                "content_hash": h, "created_at": now_iso()})
            stats["new"] += 1
    return stats


def ingest_feedback(conn: sqlite3.Connection, inbox: Path, day: date) -> dict:
    """Apply every feedback file once (by content fingerprint); records the value it replaced."""
    stats = {"files": 0, "applied": 0}
    problems: list[str] = []
    if not inbox.is_dir():
        return stats
    for path in sorted(inbox.glob("*.json")):
        ff: FeedbackFile = load_model(path, FeedbackFile)
        stats["files"] += 1
        for f in ff.feedback:
            ent = ref(*parse_ref(f.entity))
            if not entity_exists(conn, ent):
                problems.append(f"{path.name}: {ent} is not defined")
                continue
            target = relation = ""
            if f.field in ("link_add", "link_remove"):  # FeedbackIn already ran check_link
                relation, raw = split_link_value(f.value)
                ent, target = check_link(ent, raw, relation)
                if not entity_exists(conn, target):
                    problems.append(f"{path.name}: link target {target} is not defined")
                    continue
            fp = db.sha([ent, f.field, f.value, f.reason, f.author, f.at.isoformat()])
            if db.one(conn, "SELECT 1 FROM feedback WHERE fingerprint=?", (fp,)):
                continue
            old = None
            if f.field in ("decision", "priority", "lifecycle"):
                st = effective(conn, ent)
                if st is None:
                    problems.append(f"{path.name}: {ent} has no assessment yet, so its {f.field} cannot be changed")
                    continue
                old = st[f.field]
            with db.tx(conn):
                db.insert(conn, "feedback", {"at": f.at.isoformat(), "entity": ent, "field": f.field,
                                             "old_value": old, "new_value": f.value, "reason": f.reason,
                                             "author": f.author, "source_file": path.name, "fingerprint": fp})
                if target:
                    add_link_event(conn, ent, target, relation,
                                   "add" if f.field == "link_add" else "remove", f"human:{f.author}", f.reason, day)
            stats["applied"] += 1
    if problems:
        raise InputError(problems)
    return stats


def tracked_point(conn: sqlite3.Connection, state: dict, as_of: date) -> metrics.Point | None:
    """Latest observation of the state's tracked series up to `as_of`, with its measurement identity."""
    tr = state["body"].get("tracked")
    if not tr:
        return None
    pts = metrics.tracked_points(conn, tr, state["entity"], until=_end_of(as_of))
    return pts[-1] if pts else None


def day_window(day: date, days: int) -> tuple[date, date]:
    return day - timedelta(days=days), day
