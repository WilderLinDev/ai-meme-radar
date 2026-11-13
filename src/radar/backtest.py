"""Two independent backtests, both judged against what was frozen at assessment time.

1. lifecycle: did the tracked series move the way the assessed lifecycle
   implied (rising / holding / falling) over LIFECYCLE_HORIZON days?
2. decision: for opportunities, was the build / validate / monitor / skip call
   borne out by the tracked series over DECISION_HORIZON days?

The baseline is the value frozen in the assessment snapshot, never a value
looked up later. The outcome is the first observation at or after day + horizon
(within a grace window). The final revision of each assessment day is judged;
human feedback does not rewrite the agent's record, it is reported beside it.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from . import db
from .config import end_of, now_iso
from .research import metrics

LIFECYCLE_HORIZON = 7
DECISION_HORIZON = 14
GRACE = 7  # days after the horizon an outcome may still be observed
HOLD_FLOOR = -0.15
SUPPORT_FLOOR = -0.10
MISSED_RISE = 0.30


def _final(cutoff: str | None) -> tuple[str, tuple]:
    """Final revision per (day, entity) among revisions that existed at `cutoff` (created_at).

    The cutoff is applied before MAX(revision), so a revision added later never displaces the one a
    historical report saw. Without a cutoff: the final revision known now.
    """
    where, params = ("WHERE created_at <= ?", (cutoff,)) if cutoff else ("", ())
    return (f"SELECT a.* FROM assessments a JOIN (SELECT day, entity, MAX(revision) AS rev FROM assessments {where}"
            " GROUP BY day, entity) m ON a.day=m.day AND a.entity=m.entity AND a.revision=m.rev", params)


def _outcome_point(conn, tracked: dict, entity: str, day: date, horizon: int, ident: dict | None,
                   cutoff: str | None) -> metrics.Point | None:
    """First observation in the outcome window, measured like the frozen baseline, ingested by `cutoff`."""
    due = (day + timedelta(days=horizon)).isoformat()
    last = (day + timedelta(days=horizon + GRACE)).isoformat()
    for p in metrics.tracked_points(conn, tracked, entity, ident=ident, available_by=cutoff):
        if due <= p.at[:10] <= last:
            return p
    return None


def lifecycle_outcome(expected: str, change: float) -> str:
    if expected == "rising":
        return "hit" if change >= metrics.RISE else "miss"
    if expected == "falling":
        return "hit" if change <= -metrics.RISE else "miss"
    return "hit" if change > HOLD_FLOOR else "miss"


def decision_outcome(decision: str, change: float) -> str:
    if decision in ("build", "validate"):
        return "supported" if change >= SUPPORT_FLOOR else "not_supported"
    if decision == "monitor":
        return "missed_upside" if change >= MISSED_RISE else "ok"
    return "missed" if change >= MISSED_RISE else "correct"


def judge(conn: sqlite3.Connection, a: dict, system: str, horizon: int, today: date,
          cutoff: str | None) -> dict:
    """One assessment, one system, judged with what was ingested by `cutoff` (None = everything).

    `outcome_at` is when the outcome was observed; `outcome_ingested_at` is when the store got it,
    which is what decides whether a report on some day may see it as settled.
    """
    body = json.loads(a["body_json"])
    snap = json.loads(a["snapshot_json"])
    day = date.fromisoformat(a["day"])
    tracked, base = snap.get("tracked"), snap.get("baseline")
    row = {"system": system, "assessment_id": a["id"], "horizon_days": horizon, "series_json": db.dumps(tracked),
           "baseline_value": base["value"] if base else None, "baseline_at": base["at"] if base else None,
           "outcome_value": None, "outcome_at": None, "outcome_ingested_at": None, "change_pct": None}
    if not tracked or not base:
        return row | {"outcome": "unscorable", "detail": "no tracked series frozen at assessment time"}
    if not base.get("ident"):
        return row | {"outcome": "unscorable", "detail": "baseline has no measurement identity"}
    if base["value"] == 0:
        return row | {"outcome": "unscorable", "detail": "baseline is 0; change is undefined"}
    p = _outcome_point(conn, tracked, a["entity"], day, horizon, base.get("ident"), cutoff)
    if p is None:
        expired = today > day + timedelta(days=horizon + GRACE)
        return row | {"outcome": "no_data" if expired else "pending",
                      "detail": "no observation in the outcome window" if expired else
                      f"due {(day + timedelta(days=horizon)).isoformat()}"}
    change = (p.value - base["value"]) / abs(base["value"])
    row |= {"outcome_value": p.value, "outcome_at": p.at, "outcome_ingested_at": p.available_at, "change_pct": change}
    if system == "lifecycle":
        exp = body.get("expected_direction") or "holding"
        return row | {"outcome": lifecycle_outcome(exp, change), "detail": f"{a['lifecycle']} expected {exp}"}
    return row | {"outcome": decision_outcome(a["decision"], change), "detail": f"decision {a['decision']}"}


def _systems(entity: str) -> list[tuple[str, int]]:
    out = [("lifecycle", LIFECYCLE_HORIZON)]
    if entity.startswith("opportunity:"):
        out.append(("decision", DECISION_HORIZON))
    return out


def evaluate(conn: sqlite3.Connection, today: date) -> dict:
    """Store the current result of every final revision, using everything ingested so far."""
    counts: dict[str, dict[str, int]] = {"lifecycle": {}, "decision": {}}
    sql, params = _final(None)
    with db.tx(conn):
        for a in db.rows(conn, sql + " ORDER BY a.day, a.entity", params):
            for system, horizon in _systems(a["entity"]):
                row = judge(conn, a, system, horizon, today, None) | {"evaluated_at": now_iso()}
                conn.execute("INSERT OR REPLACE INTO backtest_results (system, assessment_id, horizon_days,"
                             " series_json, baseline_value, baseline_at, outcome_value, outcome_at,"
                             " outcome_ingested_at, change_pct, outcome, detail, evaluated_at) VALUES (:system,"
                             " :assessment_id, :horizon_days, :series_json, :baseline_value, :baseline_at,"
                             " :outcome_value, :outcome_at, :outcome_ingested_at, :change_pct, :outcome, :detail,"
                             " :evaluated_at)", row)
                c = counts[system]
                c[row["outcome"]] = c.get(row["outcome"], 0) + 1
    return counts


def official(conn: sqlite3.Connection, system: str | None = None, entity: str | None = None,
             as_of: date | None = None) -> list[dict]:
    """Official backtest rows: final revisions only, joined with their assessment.

    Without `as_of`: the stored results (current knowledge; superseded revisions' rows stay stored
    for audit but are not returned). With `as_of`: recomputed as that day saw it, from revisions
    created and observations ingested by the end of that day.
    """
    cutoff = end_of(as_of) if as_of else None
    sql, params = _final(cutoff)
    cols = "f.entity, f.day AS assessed_day, f.revision, f.lifecycle, f.decision"
    clauses, args = [], list(params)
    if as_of:
        clauses.append("f.day <= ?")
        args.append(as_of.isoformat())
    if entity:
        clauses.append("f.entity = ?")
        args.append(entity)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    if not as_of:
        sys_clause = (" AND b.system = ?" if where else " WHERE b.system = ?") if system else ""
        return db.rows(conn, f"SELECT b.*, {cols} FROM backtest_results b JOIN ({sql}) f ON f.id = b.assessment_id"
                             f"{where}{sys_clause} ORDER BY f.day, b.system, f.entity",
                       args + ([system] if system else []))
    out = []
    for a in db.rows(conn, f"SELECT f.*, {cols} FROM ({sql}) f{where} ORDER BY f.day, f.entity", args):
        for sysname, horizon in _systems(a["entity"]):
            if system and sysname != system:
                continue
            out.append(judge(conn, a, sysname, horizon, as_of, cutoff) |
                       {k: a[k] for k in ("entity", "assessed_day", "revision", "lifecycle", "decision")})
    out.sort(key=lambda r: (r["assessed_day"], r["system"], r["entity"]))
    return out


GOOD = {"lifecycle": {"hit"}, "decision": {"supported", "ok", "correct"}}
BAD = {"lifecycle": {"miss"}, "decision": {"not_supported", "missed_upside", "missed"}}


def summary(conn: sqlite3.Connection, as_of: date | None = None) -> dict:
    out = {}
    for system in ("lifecycle", "decision"):
        c: dict[str, int] = {}
        for r in official(conn, system=system, as_of=as_of):
            c[r["outcome"]] = c.get(r["outcome"], 0) + 1
        good = sum(v for k, v in c.items() if k in GOOD[system])
        bad = sum(v for k, v in c.items() if k in BAD[system])
        out[system] = {"counts": c, "scored": good + bad, "good": good,
                       "rate": good / (good + bad) if good + bad else None}
    return out


def resolved_on(conn: sqlite3.Connection, day: date) -> list[dict]:
    """Outcomes that became settled on `day`: ingested that day (observed then or earlier).

    A metric observed on the 20th and ingested on the 22nd settles on the 22nd; its outcome_at stays the 20th.
    """
    return [r for r in official(conn, as_of=day)
            if r["outcome_ingested_at"] and r["outcome_ingested_at"][:10] == day.isoformat()]
