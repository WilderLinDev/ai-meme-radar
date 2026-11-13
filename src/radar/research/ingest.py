"""Load the agent's research file into SQLite, refusing anything that can't be checked.

Checks, all reported at once:
* every referenced trend / format / opportunity exists (in this file or the store);
* a new entity whose name or alias matches an existing one of the same kind is a
  duplicate: reuse the existing id;
* evidence citing an `api_call_id` points at a successful recorded call, and a
  numeric value tagged 已核实 or 第三方读数 actually appears in that response.
Ingest is idempotent: rerunning the same file changes nothing.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from .. import db
from ..config import TZ, end_of, now_iso, today
from ..text import norm_key, parse_ref, ref
from .models import EvidenceIn, ResearchFile


class InputError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def load_model(path: Path, model):
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as e:
        raise InputError([f"{path.name}: {'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                          for err in e.errors()]) from None
    except FileNotFoundError:
        raise InputError([f"{path} does not exist"]) from None


def entity_exists(conn: sqlite3.Connection, r: str) -> bool:
    kind, ident = parse_ref(r)
    if kind in ("keyword", "site"):
        return True
    return db.one(conn, "SELECT 1 FROM entities WHERE kind=? AND id=?", (kind, ident)) is not None


def current_links(conn: sqlite3.Connection, as_of: date | str | None = None) -> dict[tuple[str, str, str], dict]:
    """Effective links: replay the append-only link events in insertion order (id).

    `as_of` (a report day, or an exact ingestion timestamp) keeps only events actually recorded by then
    (`at`), whatever research `day` they were filed under.
    """
    out: dict[tuple[str, str, str], dict] = {}
    sql, params = "SELECT * FROM link_events", ()
    if as_of:
        sql, params = sql + " WHERE at <= ?", (end_of(as_of) if isinstance(as_of, date) else as_of,)
    for e in db.rows(conn, sql + " ORDER BY id", params):
        k = (e["src"], e["dst"], e["relation"])
        if e["action"] == "add":
            out[k] = e
        else:
            out.pop(k, None)
    return out


def add_link_event(conn: sqlite3.Connection, src: str, dst: str, relation: str, action: str, origin: str,
                   note: str, day: date) -> bool:
    live = (src, dst, relation) in current_links(conn)
    if (action == "add") == live:
        return False
    db.insert(conn, "link_events", {"src": src, "dst": dst, "relation": relation, "action": action,
                                    "origin": origin, "note": note, "day": day.isoformat(), "at": now_iso()})
    return True


def _numbers(obj) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        try:
            out.append(float(obj.replace(",", "")))
        except ValueError:
            pass
    elif isinstance(obj, dict):
        for v in obj.values():
            out += _numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _numbers(v)
    return out


def value_in_call(conn: sqlite3.Connection, call_id: int, value: float) -> bool | None:
    r = db.one(conn, "SELECT ok, response_json FROM api_calls WHERE id=?", (call_id,))
    if not r or not r["ok"]:
        return None
    nums = _numbers(json.loads(r["response_json"] or "null"))
    return any(math.isclose(n, value, rel_tol=0.005, abs_tol=1e-9) for n in nums)


def _keys(kind: str, ident: str, name: str, aliases: list[str]) -> set[str]:
    return {f"{kind}|{norm_key(x)}" for x in (ident.replace("-", " "), name, *aliases) if norm_key(x)}


# Every persisted field that carries meaning. Excluded: id (generated) and day (when it was ingested).
EVIDENCE_FIELDS = ("ref", "entity", "channel", "source", "url", "metric", "value", "unit", "region", "sample_size",
                   "metric_definition", "collected_at", "confidence", "tag", "api_call_id", "note")


def evidence_record(e: EvidenceIn) -> dict:
    """Canonical stored form: normalized ref, entity and region, float value, Asia/Shanghai timestamp."""
    return {"ref": e.ref or None, "entity": ref(*parse_ref(e.entity)), "channel": e.channel, "source": e.source,
            "url": e.url, "metric": e.metric, "value": float(e.value) if e.value is not None else None,
            "unit": e.unit, "region": e.region.upper(), "sample_size": e.sample_size,
            "metric_definition": e.metric_definition, "collected_at": e.collected_at.astimezone(TZ).isoformat(),
            "confidence": e.confidence, "tag": e.tag, "api_call_id": e.api_call_id, "note": e.note}


def evidence_fingerprint(rec: dict) -> str:
    return db.sha({k: rec[k] for k in EVIDENCE_FIELDS})


def ingest_research(conn: sqlite3.Connection, path: Path, day: date) -> dict:
    rf: ResearchFile = load_model(path, ResearchFile)
    problems: list[str] = []
    if rf.day != day:
        problems.append(f"{path.name}: day is {rf.day}, expected {day}")

    nodes = [("trend", t) for t in rf.trends] + [("format", f) for f in rf.formats] + \
            [("opportunity", o) for o in rf.opportunities]
    declared = {ref(k, n.id) for k, n in nodes}

    # dedupe against the store and within the file
    claimed: dict[str, str] = {}
    for kind, n in nodes:
        for key in _keys(kind, n.id, n.name, n.aliases):
            owner = db.one(conn, "SELECT kind, id FROM entity_keys WHERE norm=?", (key,))
            if owner and owner["id"] != n.id:
                problems.append(f"{kind}:{n.id} duplicates existing {owner['kind']}:{owner['id']} "
                                f"(shared name/alias {key.split('|', 1)[1]!r}); reuse that id")
            other = claimed.get(key)
            if other and other != n.id:
                problems.append(f"{kind}:{n.id} and {kind}:{other} share name/alias {key.split('|', 1)[1]!r}")
            claimed[key] = n.id

    def known(r: str) -> bool:
        return r in declared or entity_exists(conn, r)

    for l in rf.links:
        for side in (l.src, l.dst):
            if not known(side):
                problems.append(f"link {l.src}->{l.dst}: {side} is not defined")
    for e in rf.evidence:
        if not known(e.entity):
            problems.append(f"evidence {e.ref or e.source}: {e.entity} is not defined")
        if e.api_call_id is not None:
            found = value_in_call(conn, e.api_call_id, e.value) if e.value is not None else True
            if found is None:
                problems.append(f"evidence {e.ref or e.source}: api_call_id {e.api_call_id} is not a successful call")
            elif found is False and e.tag != "估算":
                problems.append(f"evidence {e.ref or e.source}: value {e.value} does not appear in call "
                                f"{e.api_call_id}; tag it 估算 if derived, or fix it")
        if e.ref:
            held = db.one(conn, "SELECT day, fingerprint FROM evidence WHERE ref=?", (e.ref,))
            if held and held["fingerprint"] != evidence_fingerprint(evidence_record(e)):
                problems.append(f"evidence ref {e.ref} already names different evidence (ingested {held['day']}); "
                                f"refs are global and permanent: use a new ref")
    if problems:
        raise InputError(problems)

    stats = {"entities": 0, "links": 0, "evidence": 0, "gaps": 0, "metadata": 0}
    at = now_iso()
    with db.tx(conn):
        for kind, n in nodes:
            data = n.model_dump(exclude={"id", "name"})
            prev = db.one(conn, "SELECT data_json, name FROM entities WHERE kind=? AND id=?", (kind, n.id))
            if prev is None:
                db.insert(conn, "entities", {"kind": kind, "id": n.id, "name": n.name, "data_json": db.dumps(data),
                                             "first_seen_day": day.isoformat(), "updated_day": day.isoformat()})
                stats["entities"] += 1
            elif prev["data_json"] != db.dumps(data) or prev["name"] != n.name:
                conn.execute("UPDATE entities SET name=?, data_json=?, updated_day=? WHERE kind=? AND id=?",
                             (n.name, db.dumps(data), day.isoformat(), kind, n.id))
                stats["entities"] += 1
            for key in _keys(kind, n.id, n.name, n.aliases):
                conn.execute("INSERT OR IGNORE INTO entity_keys (norm, kind, id) VALUES (?,?,?)", (key, kind, n.id))
        for l in rf.links:
            s = ref(*parse_ref(l.src))
            d = ref(*parse_ref(l.dst))
            if add_link_event(conn, s, d, l.relation, "add", "agent", l.note, day):
                stats["links"] += 1
        for e in rf.evidence:
            rec = evidence_record(e)
            cols = ["day", *EVIDENCE_FIELDS, "ingested_at", "fingerprint"]
            # fingerprint conflict = identical evidence already stored (idempotent); a ref clash with
            # different content was rejected above and would also violate the unique ref index
            cur = conn.execute(
                f"INSERT INTO evidence ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
                " ON CONFLICT(fingerprint) DO NOTHING",
                (day.isoformat(), *(rec[k] for k in EVIDENCE_FIELDS), at, evidence_fingerprint(rec)))
            stats["evidence"] += cur.rowcount
        for g in rf.gaps:
            stats["gaps"] += record_gap(conn, day, g.source, g.note, "agent")
        for c in rf.social_coverage:  # incomplete coverage is a gap too, so it is never silent
            if c.status != "covered":
                stats["gaps"] += record_gap(conn, day, f"社交调研：{c.platform}", f"{c.status}：{c.note}", "coverage")
        # the day's research metadata: one row per day, replaced (and re-timestamped) only when it changes
        coverage = db.dumps([c.model_dump() for c in rf.social_coverage])
        meta = db.one(conn, "SELECT notes, social_coverage_json FROM research_days WHERE day=?", (day.isoformat(),))
        if not meta or (meta["notes"], meta["social_coverage_json"]) != (rf.notes, coverage):
            conn.execute("INSERT OR REPLACE INTO research_days (day, notes, social_coverage_json, updated_at)"
                         " VALUES (?,?,?,?)", (day.isoformat(), rf.notes, coverage, at))
            stats["metadata"] += 1
        refuse_backdated(day, stats, path.name)  # raising here rolls the whole file back
    return stats


def refuse_backdated(day: date, stats: dict, what: str) -> None:
    """Research for a day can only be written on that day (Asia/Shanghai).

    Ingestion time is what proves the store knew something by a report's cutoff, so a record filed
    under another research day would make that day's report wrong. Re-ingesting identical content
    writes nothing and is allowed on any day; anything new for a past or future day is refused.
    """
    if day != today() and any(stats.values()):
        raise InputError([f"{what}: would write {', '.join(f'{v} {k}' for k, v in stats.items() if v)} for "
                          f"research day {day}, but today is {today()} (Asia/Shanghai). Backdated or future "
                          f"research is not accepted: file it under today's research day."])


def record_gap(conn: sqlite3.Connection, day: date, source: str, note: str, origin: str = "code") -> int:
    """A gap belongs to research day `day`; ingested_at says when the store learned of it."""
    return conn.execute("INSERT OR IGNORE INTO gaps (day, source, note, origin, ingested_at) VALUES (?,?,?,?,?)",
                        (day.isoformat(), source, note, origin, now_iso())).rowcount
