"""Unified candidate list for the day: what code can find before the agent looks.

Channels code can read on its own (social is the agent's, in the browser):
* search  - Ge Fei emerging keywords (new / resurgence / spike / watch)
* product - new-site launches and website discovery (hosted) in the creative space
* market  - revenue-tracked sites in the creative space

Candidates from different channels that share a keyword or a domain are merged
into one group. Each group lists the existing entities it already matches, and
the file also carries link suggestions (trend search terms -> keywords / sites)
and the refresh list of live entities. The agent decides what any of it means.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import db
from ..config import REPO, TZ, research_terms
from ..decisions import all_effective, is_key
from ..text import Vocabulary, domain_of, keyword_key, norm_key, ref, term_matches
from .ingest import current_links

KIND_ORDER = {"new": 0, "resurgence": 1, "spike": 2, "watch": 3, "old": 4}
PER_CHANNEL = 150


def _since(conn: sqlite3.Connection, day: date) -> str:
    r = db.one(conn, "SELECT at FROM run_events WHERE stage='discover' AND event='done' AND day < ?"
                     " ORDER BY id DESC LIMIT 1", (day.isoformat(),))
    if r:
        return r["at"]
    return (datetime.combine(day, datetime.min.time(), TZ) - timedelta(days=7)).isoformat()


class Matcher:
    def __init__(self, conn: sqlite3.Connection):
        terms = research_terms()
        self.vocab = Vocabulary(terms.get("creative_terms", []))
        self.cats = Vocabulary(terms.get("creative_categories", []))
        self.keys = {r["norm"]: ref(r["kind"], r["id"]) for r in db.rows(conn, "SELECT * FROM entity_keys")}
        self.terms: list[tuple[str, str]] = []
        for e in db.rows(conn, "SELECT kind, id, name, data_json FROM entities WHERE kind IN ('trend','opportunity')"):
            data = json.loads(e["data_json"])
            for t in [e["name"], *data.get("search_terms", []), *data.get("aliases", [])]:
                if t:
                    self.terms.append((t, ref(e["kind"], e["id"])))

    def creative(self, *texts, category: str | None = None) -> list[str]:
        return self.vocab.hits(*texts) + (self.cats.hits(category) if category else [])

    def entities_for(self, text: str) -> list[str]:
        hits = {v for k, v in self.keys.items() if k.split("|", 1)[1] == norm_key(text)}
        hits |= {r for t, r in self.terms if term_matches(t, text)}
        return sorted(hits)


def search_candidates(conn, m: Matcher, since: str) -> list[dict]:
    out = {}
    for r in db.rows(conn, "SELECT s.*, k.display, k.category FROM keyword_snapshots s JOIN keywords k USING(keyword)"
                           " WHERE s.captured_at >= ? ORDER BY s.id", (since,)):
        data = json.loads(r["data_json"])
        hits = m.creative(r["display"], (data.get("brief") or {}).get("what"), category=r["category"])
        if not hits:
            continue
        out[r["keyword"]] = {
            "channel": "search", "keyword": r["display"], "kind": r["kind"], "heat_ratio": r["heat_ratio"],
            "growth_pct": r["growth_pct"], "trend_now": r["trend_now"], "appear_date": r["appear_date"],
            "burst_date": r["burst_date"], "gefei_verdict": r["verdict"],
            "gefei_suggestion": r["verdict_suggestion"], "brief": data.get("brief"), "page_url": data.get("page_url"),
            "batch_id": r["batch_id"], "call_id": r["call_id"], "matched_terms": hits}
    rows = sorted(out.values(), key=lambda c: (KIND_ORDER.get(c["kind"] or "", 9), -(c["growth_pct"] or 0)))
    return rows[:PER_CHANNEL]


def product_candidates(conn, m: Matcher, since: str) -> list[dict]:
    out = []
    for r in db.rows(conn, "SELECT * FROM launches WHERE captured_at >= ? ORDER BY posted_at DESC", (since,)):
        hits = m.creative(r["title"], r["purpose"], r["keyword"], r["domain"], category=r["category"])
        if hits:
            out.append({"channel": "product", "source": f"launch:{r['source']}", "domain": r["domain"],
                        "title": r["title"], "url": r["url"], "purpose": r["purpose"], "category": r["category"],
                        "keyword": r["keyword"], "monetization": r["monetization"], "audience": r["audience"],
                        "motive_type": r["motive_type"], "monthly_traffic": r["monthly_traffic"],
                        "domain_registered": r["domain_registered"], "posted_at": r["posted_at"],
                        "call_id": r["call_id"], "matched_terms": hits})
    for r in db.rows(conn, "SELECT * FROM hosted_site_snapshots WHERE captured_at >= ? AND period='default'"
                           " ORDER BY latest28_clicks DESC", (since,)):
        hits = m.creative(r["title"], r["description"], r["site"])
        if hits:
            data = json.loads(r["data_json"])
            out.append({"channel": "product", "source": f"hosted:{r['platform']}", "domain": domain_of(r["site"]),
                        "title": r["title"], "description": r["description"],
                        "latest28_clicks": r["latest28_clicks"], "peak_clicks": r["peak_clicks"],
                        "top_keywords": data.get("top_keywords"), "first_period": data.get("first_period"),
                        "call_id": r["call_id"], "matched_terms": hits})
    return out[:PER_CHANNEL]


def market_candidates(conn, m: Matcher, since: str) -> list[dict]:
    out = []
    for r in db.rows(conn, "SELECT r.* FROM revenue_site_snapshots r JOIN sites s ON s.domain = r.domain"
                           " WHERE r.captured_at >= ? ORDER BY r.global_rank IS NULL, r.global_rank", (since,)):
        hits = m.creative(r["domain"], category=r["category"])
        if hits:
            data = json.loads(r["data_json"])
            out.append({"channel": "market", "domain": r["domain"], "month": r["month"], "period": r["period"],
                        "global_rank": r["global_rank"], "category": r["category"],
                        "traffic": data.get("traffic"), "channels": data.get("channels"),
                        "note": "估算访问量，不是营收", "call_id": r["call_id"], "matched_terms": hits})
    return out[:PER_CHANNEL]


def _keys_of(c: dict) -> list[str]:
    keys = []
    if c.get("keyword") and keyword_key(c["keyword"]):
        keys.append("kw|" + keyword_key(c["keyword"]))
    if c.get("domain"):
        keys.append("site|" + c["domain"])
    return keys


def group(cands: list[dict], m: Matcher) -> list[dict]:
    """Connected components of candidates linked by a shared keyword key or domain (transitively)."""
    parent = list(range(len(cands)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[str, int] = {}
    for i, c in enumerate(cands):
        for k in _keys_of(c):
            if k in owner:
                a, b = find(owner[k]), find(i)
                if a != b:
                    parent[max(a, b)] = min(a, b)  # smallest index stays root: deterministic
            else:
                owner[k] = i
    members: dict[int, list[int]] = {}
    for i in range(len(cands)):
        members.setdefault(find(i), []).append(i)
    groups = []
    for root in sorted(members):
        items = [cands[i] for i in members[root]]
        first = items[0]
        keys: list[str] = []
        channels: list[str] = []
        for c in items:
            keys += [k for k in _keys_of(c) if k not in keys]
            if c["channel"] not in channels:
                channels.append(c["channel"])
        texts = [t for c in items for t in (c.get("keyword"), c.get("title")) if t]
        groups.append({"label": first.get("keyword") or first.get("title") or first.get("domain") or "?",
                       "keys": keys, "channels": channels, "items": items,
                       "matches": sorted({r for t in texts for r in m.entities_for(t)})})
    groups.sort(key=lambda g: (-len(g["channels"]), not g["matches"], g["label"], g["keys"]))
    return groups


def link_suggestions(conn, m: Matcher) -> list[dict]:
    links = current_links(conn)
    live = {(s, d) for (s, d, _) in links}
    out = []
    kws = db.rows(conn, "SELECT keyword, display FROM keywords")
    sites = db.rows(conn, "SELECT site AS domain, MAX(title) AS title, MAX(description) AS description"
                          " FROM hosted_site_snapshots GROUP BY site")
    sites += db.rows(conn, "SELECT domain, MAX(title) AS title, MAX(purpose) AS description FROM launches"
                           " WHERE domain IS NOT NULL GROUP BY domain")
    for term, ent in m.terms:
        for k in kws:
            if term_matches(term, k["display"]) and (ent, ref("keyword", k["keyword"])) not in live:
                rel = "searched_as" if ent.startswith("trend:") else "targets"
                out.append({"from": ent, "to": ref("keyword", k["keyword"]), "relation": rel, "because": term})
        for s in sites:
            text = " ".join(x for x in (s["title"], s["description"]) if x)
            if text and term_matches(term, text) and (ent, ref("site", domain_of(s["domain"]))) not in live:
                out.append({"from": ent, "to": ref("site", domain_of(s["domain"])), "relation": "competitor",
                            "because": term})
    seen, uniq = set(), []
    for s in out:
        k = (s["from"], s["to"])
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return uniq[:300]


def refresh_list(conn, day: date) -> list[dict]:
    out = []
    for st in all_effective(conn, day):
        if st["decision"] == "skip" and not is_key(st):
            continue
        last = db.one(conn, "SELECT MAX(collected_at) AS at FROM evidence WHERE entity=?", (st["entity"],))
        out.append({"entity": st["entity"], "lifecycle": st["lifecycle"], "decision": st["decision"],
                    "priority": st["priority"], "last_evidence_at": last["at"] if last else None,
                    "search_terms": json.loads((db.one(conn, "SELECT data_json FROM entities WHERE kind=? AND id=?",
                                                       st["entity"].split(":", 1)) or {"data_json": "{}"})
                                               ["data_json"]).get("search_terms", [])})
    out.sort(key=lambda x: (x["priority"], x["last_evidence_at"] or ""))
    return out


def query_hints(conn, day: date) -> list[dict]:
    """Entities with search terms but no search evidence in 7 days: suggested (not executed) calls."""
    out = []
    cutoff = (day - timedelta(days=7)).isoformat()
    for e in db.rows(conn, "SELECT kind, id, data_json FROM entities WHERE kind IN ('trend','opportunity')"):
        terms = json.loads(e["data_json"]).get("search_terms", [])
        r = ref(e["kind"], e["id"])
        if not terms:
            continue
        recent = db.one(conn, "SELECT 1 FROM evidence WHERE entity=? AND channel='search' AND day >= ?", (r, cutoff))
        if not recent:
            out.append({"entity": r, "calls": [
                {"tool": "keyword_volume", "params": {"keywords": terms[:50], "gl": "us"}},
                {"tool": "google_trends", "params": {"keyword": terms[0], "geo": "US"}},
                {"tool": "serp", "params": {"q": terms[0], "gl": "us"}}]})
    return out


def discover(conn: sqlite3.Connection, day: date, out: Path) -> dict:
    since = _since(conn, day)
    m = Matcher(conn)
    cands = search_candidates(conn, m, since) + product_candidates(conn, m, since) + market_candidates(conn, m, since)
    groups = group(cands, m)
    doc = {
        "day": day.isoformat(), "since": since,
        "note": "Code-found candidates (search/product/market). Social discovery is the agent's job; merge both "
                "into research.json. Nothing here is a judgment.",
        "groups": groups,
        "link_suggestions": link_suggestions(conn, m),
        "refresh": refresh_list(conn, day),
        "query_hints": query_hints(conn, day),
        "watchlist": str(REPO / "config" / "watchlist.csv"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return {"groups": len(groups), "search": sum(1 for c in cands if c["channel"] == "search"),
            "product": sum(1 for c in cands if c["channel"] == "product"),
            "market": sum(1 for c in cands if c["channel"] == "market"),
            "link_suggestions": len(doc["link_suggestions"]), "refresh": len(doc["refresh"])}
