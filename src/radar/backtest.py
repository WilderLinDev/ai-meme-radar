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
from .config import now_iso
from .research import metrics

LIFECYCLE_HORIZON = 7
DECISION_HORIZON = 14
GRACE = 7  # days after the horizon an outcome may still be observed
HOLD_FLOOR = -0.15
SUPPORT_FLOOR = -0.10
MISSED_RISE = 0.30


# The official set: the final revision of each (day, entity). Results of superseded revisions stay
# stored for audit but never count in summaries or resolutions.
FINAL = ("SELECT a.* FROM assessments a JOIN (SELECT day, entity, MAX(revision) AS rev FROM assessments"
         " GROUP BY day, entity) m ON a.day=m.day AND a.entity=m.entity AND a.revision=m.rev")


def _judged(conn: sqlite3.Connection) -> list[dict]:
    return db.rows(conn, FINAL + " ORDER BY a.day, a.entity")


def official(conn: sqlite3.Connection, where: str = "", params: tuple = (), as_of: date | None = None) -> list[dict]:
    """Backtest rows of final revisions only, joined with their assessment.

    With `as_of`, only assessments made by that day, each shown as it stood that day: an outcome counts
    as settled only if its observation had been ingested by then (`outcome_day <= as_of`); otherwise it
    is pending, or no_data once the window had closed. The stored row itself is not changed.
    """
    sql = (f"SELECT b.*, f.entity, f.day AS assessed_day, f.revision, f.lifecycle, f.decision"
           f" FROM backtest_results b JOIN ({FINAL}) f ON f.id = b.assessment_id")
    clauses, args = ([where] if where else []), list(params)
    if as_of:
        clauses.append("f.day <= ?")
        args.append(as_of.isoformat())
    out = db.rows(conn, sql + (" WHERE " + " AND ".join(clauses) if clauses else "")
                  + " ORDER BY f.day, b.system, f.entity", args)
    return [as_of_view(r, as_of) for r in out] if as_of else out


def as_of_view(r: dict, as_of: date) -> dict:
    if r["outcome"] == "unscorable" or (r["outcome_day"] and r["outcome_day"] <= as_of.isoformat()):
        return r
    closed = as_of > date.fromisoformat(r["assessed_day"]) + timedelta(days=r["horizon_days"] + GRACE)
    return r | {"outcome": "no_data" if closed else "pending", "outcome_value": None, "outcome_at": None,
                "outcome_day": None, "change_pct": None}


def _outcome_point(conn, tracked: dict, entity: str, day: date, horizon: int,
                   ident: dict | None) -> metrics.Point | None:
    """First observation in the outcome window measured exactly like the frozen baseline."""
    due = (day + timedelta(days=horizon)).isoformat()
    last = (day + timedelta(days=horizon + GRACE)).isoformat()
    for p in metrics.tracked_points(conn, tracked, entity, ident=ident):
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


def evaluate(conn: sqlite3.Connection, today: date) -> dict:
    counts: dict[str, dict[str, int]] = {"lifecycle": {}, "decision": {}}
    with db.tx(conn):
        for a in _judged(conn):
            body = json.loads(a["body_json"])
            snap = json.loads(a["snapshot_json"])
            day = date.fromisoformat(a["day"])
            systems = [("lifecycle", LIFECYCLE_HORIZON)]
            if a["entity"].startswith("opportunity:"):
                systems.append(("decision", DECISION_HORIZON))
            for system, horizon in systems:
                tracked, base = snap.get("tracked"), snap.get("baseline")
                row = {"system": system, "assessment_id": a["id"], "horizon_days": horizon,
                       "series_json": db.dumps(tracked), "baseline_value": base["value"] if base else None,
                       "baseline_at": base["at"] if base else None, "outcome_value": None, "outcome_at": None,
                       "outcome_day": None,
                       "change_pct": None, "evaluated_at": now_iso()}
                if not tracked or not base:
                    row |= {"outcome": "unscorable", "detail": "no tracked series frozen at assessment time"}
                elif not base.get("ident"):
                    row |= {"outcome": "unscorable", "detail": "baseline has no measurement identity"}
                elif base["value"] == 0:
                    row |= {"outcome": "unscorable", "detail": "baseline is 0; change is undefined"}
                else:
                    p = _outcome_point(conn, tracked, a["entity"], day, horizon, base.get("ident"))
                    if p is None:
                        expired = today > day + timedelta(days=horizon + GRACE)
                        row |= {"outcome": "no_data" if expired else "pending",
                                "detail": "no observation in the outcome window" if expired else
                                f"due {(day + timedelta(days=horizon)).isoformat()}"}
                    else:
                        change = (p.value - base["value"]) / abs(base["value"])
                        row |= {"outcome_value": p.value, "outcome_at": p.at, "outcome_day": p.day,
                                "change_pct": change}
                        if system == "lifecycle":
                            exp = body.get("expected_direction") or "holding"
                            row |= {"outcome": lifecycle_outcome(exp, change),
                                    "detail": f"{a['lifecycle']} expected {exp}"}
                        else:
                            row |= {"outcome": decision_outcome(a["decision"], change),
                                    "detail": f"decision {a['decision']}"}
                conn.execute("INSERT OR REPLACE INTO backtest_results (system, assessment_id, horizon_days,"
                             " series_json, baseline_value, baseline_at, outcome_value, outcome_at, outcome_day, change_pct,"
                             " outcome, detail, evaluated_at) VALUES (:system, :assessment_id, :horizon_days,"
                             " :series_json, :baseline_value, :baseline_at, :outcome_value, :outcome_at, :outcome_day,"
                             " :change_pct, :outcome, :detail, :evaluated_at)", row)
                c = counts[system]
                c[row["outcome"]] = c.get(row["outcome"], 0) + 1
    return counts


GOOD = {"lifecycle": {"hit"}, "decision": {"supported", "ok", "correct"}}
BAD = {"lifecycle": {"miss"}, "decision": {"not_supported", "missed_upside", "missed"}}


def summary(conn: sqlite3.Connection, as_of: date | None = None) -> dict:
    out = {}
    for system in ("lifecycle", "decision"):
        c: dict[str, int] = {}
        for r in official(conn, "b.system=?", (system,), as_of):
            c[r["outcome"]] = c.get(r["outcome"], 0) + 1
        good = sum(v for k, v in c.items() if k in GOOD[system])
        bad = sum(v for k, v in c.items() if k in BAD[system])
        out[system] = {"counts": c, "scored": good + bad, "good": good,
                       "rate": good / (good + bad) if good + bad else None}
    return out


def resolved_on(conn: sqlite3.Connection, day: date) -> list[dict]:
    """Official results whose outcome observation fell on `day` and was known by then (newly scored)."""
    return official(conn, "substr(b.outcome_at,1,10)=?", (day.isoformat(),), as_of=day)
