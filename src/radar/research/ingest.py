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
from ..config import now_iso
from ..text import norm_key, parse_ref, ref
from .models import ResearchFile


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


def current_links(conn: sqlite3.Connection) -> dict[tuple[str, str, str], dict]:
    """Latest event per (src, dst, relation) that is an add."""
    out: dict[tuple[str, str, str], dict] = {}
    for e in db.rows(conn, "SELECT * FROM link_events ORDER BY id"):
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
        if e.ref and db.one(conn, "SELECT 1 FROM evidence WHERE ref=? AND day!=?", (e.ref, day.isoformat())):
            problems.append(f"evidence ref {e.ref} was already used on another day; refs are global")
    if problems:
        raise InputError(problems)

    stats = {"entities": 0, "links": 0, "evidence": 0, "gaps": 0}
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
            ent = ref(*parse_ref(e.entity))
            row = e.model_dump()
            row["entity"] = ent
            row["collected_at"] = e.collected_at.isoformat()
            fp = db.sha({k: row[k] for k in ("entity", "source", "url", "metric", "value", "region", "collected_at",
                                             "note")})
            cur = conn.execute(
                "INSERT OR IGNORE INTO evidence (day, ref, entity, channel, source, url, metric, value, unit, region,"
                " sample_size, metric_definition, collected_at, confidence, tag, api_call_id, note, fingerprint)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (day.isoformat(), e.ref or None, ent, e.channel, e.source, e.url, e.metric, e.value, e.unit,
                 e.region.upper(), e.sample_size, e.metric_definition, row["collected_at"], e.confidence, e.tag,
                 e.api_call_id, e.note, fp))
            stats["evidence"] += cur.rowcount
        for g in rf.gaps:
            cur = conn.execute("INSERT OR IGNORE INTO gaps (day, source, note, origin) VALUES (?,?,?,?)",
                               (day.isoformat(), g.source, g.note, "agent"))
            stats["gaps"] += cur.rowcount
    return stats


def record_gap(conn: sqlite3.Connection, day: date, source: str, note: str, origin: str = "code") -> None:
    conn.execute("INSERT OR IGNORE INTO gaps (day, source, note, origin) VALUES (?,?,?,?)",
                 (day.isoformat(), source, note, origin))
