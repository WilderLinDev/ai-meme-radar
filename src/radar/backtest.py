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


def _judged(conn: sqlite3.Connection) -> list[dict]:
    """Final revision per (day, entity)."""
    return db.rows(conn, "SELECT a.* FROM assessments a JOIN (SELECT day, entity, MAX(revision) AS rev FROM assessments"
                         " GROUP BY day, entity) m ON a.day=m.day AND a.entity=m.entity AND a.revision=m.rev"
                         " ORDER BY a.day, a.entity")


def _outcome_point(conn, tracked: dict, entity: str, day: date, horizon: int) -> metrics.Point | None:
    due = (day + timedelta(days=horizon)).isoformat()
    last = (day + timedelta(days=horizon + GRACE)).isoformat()
    for p in metrics.tracked_points(conn, tracked, entity):
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
                       "change_pct": None, "evaluated_at": now_iso()}
                if not tracked or not base:
                    row |= {"outcome": "unscorable", "detail": "no tracked series frozen at assessment time"}
                elif base["value"] == 0:
                    row |= {"outcome": "unscorable", "detail": "baseline is 0; change is undefined"}
                else:
                    p = _outcome_point(conn, tracked, a["entity"], day, horizon)
                    if p is None:
                        expired = today > day + timedelta(days=horizon + GRACE)
                        row |= {"outcome": "no_data" if expired else "pending",
                                "detail": "no observation in the outcome window" if expired else
                                f"due {(day + timedelta(days=horizon)).isoformat()}"}
                    else:
                        change = (p.value - base["value"]) / abs(base["value"])
                        row |= {"outcome_value": p.value, "outcome_at": p.at, "change_pct": change}
                        if system == "lifecycle":
                            exp = body.get("expected_direction") or "holding"
                            row |= {"outcome": lifecycle_outcome(exp, change),
                                    "detail": f"{a['lifecycle']} expected {exp}"}
                        else:
                            row |= {"outcome": decision_outcome(a["decision"], change),
                                    "detail": f"decision {a['decision']}"}
                conn.execute("INSERT OR REPLACE INTO backtest_results (system, assessment_id, horizon_days,"
                             " series_json, baseline_value, baseline_at, outcome_value, outcome_at, change_pct,"
                             " outcome, detail, evaluated_at) VALUES (:system, :assessment_id, :horizon_days,"
                             " :series_json, :baseline_value, :baseline_at, :outcome_value, :outcome_at,"
                             " :change_pct, :outcome, :detail, :evaluated_at)", row)
                c = counts[system]
                c[row["outcome"]] = c.get(row["outcome"], 0) + 1
    return counts


GOOD = {"lifecycle": {"hit"}, "decision": {"supported", "ok", "correct"}}
BAD = {"lifecycle": {"miss"}, "decision": {"not_supported", "missed_upside", "missed"}}


def summary(conn: sqlite3.Connection) -> dict:
    out = {}
    for system in ("lifecycle", "decision"):
        rows = db.rows(conn, "SELECT outcome, COUNT(*) AS n FROM backtest_results WHERE system=? GROUP BY outcome",
                       (system,))
        c = {r["outcome"]: r["n"] for r in rows}
        good = sum(v for k, v in c.items() if k in GOOD[system])
        bad = sum(v for k, v in c.items() if k in BAD[system])
        out[system] = {"counts": c, "scored": good + bad, "good": good,
                       "rate": good / (good + bad) if good + bad else None}
    return out


def resolved_on(conn: sqlite3.Connection, day: date) -> list[dict]:
    """Results whose outcome observation fell on `day` (newly scored)."""
    return db.rows(conn, "SELECT b.*, a.entity, a.day AS assessed_day, a.lifecycle, a.decision FROM backtest_results b"
                         " JOIN assessments a ON a.id=b.assessment_id WHERE substr(b.outcome_at,1,10)=?"
                         " ORDER BY b.system, a.entity", (day.isoformat(),))
