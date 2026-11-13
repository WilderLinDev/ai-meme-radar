"""Raw Ge Fei responses -> normalized snapshot rows.

A snapshot row is inserted only when its content differs from the latest row
for the same identity, so repeated syncs keep history without duplicating it.
Ge Fei's own analysis (verdicts, briefs, motives, categories) is kept as-is in
the normalized rows; our conclusions live elsewhere.
"""
from __future__ import annotations

import json
import sqlite3

from .. import db
from ..config import now_iso
from ..text import domain_of, keyword_key

KEYWORD_FIELDS = ("kind", "trend_now", "heat_ratio", "growth_pct", "appear_date", "burst_date", "pushed_on",
                  "page_count", "targeted_count", "verdict", "verdict_suggestion")


def slug_from_url(url: str | None) -> str | None:
    """NEW keyword pages end in /<slug>; used when a batch row carries no slug."""
    if not url:
        return None
    tail = url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    return tail or None


def _changed(conn: sqlite3.Connection, table: str, where: str, params: tuple, row_hash: str) -> bool:
    last = db.one(conn, f"SELECT row_hash FROM {table} WHERE {where} ORDER BY id DESC LIMIT 1", params)
    return not last or last["row_hash"] != row_hash


def touch_keyword(conn: sqlite3.Connection, text: str, slug: str | None = None, category: str | None = None) -> str:
    key = keyword_key(text)
    if not key:
        return ""
    at = now_iso()
    conn.execute(
        "INSERT INTO keywords (keyword, display, slug, category, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(keyword) DO UPDATE SET last_seen_at=excluded.last_seen_at,"
        " slug=COALESCE(excluded.slug, keywords.slug), category=COALESCE(NULLIF(excluded.category,''), keywords.category)",
        (key, text.strip(), slug or None, category or "", at, at))
    return key


def touch_site(conn: sqlite3.Connection, domain: str, source: str) -> str:
    d = domain_of(domain)
    if not d:
        return ""
    at = now_iso()
    r = db.one(conn, "SELECT sources_json FROM sites WHERE domain=?", (d,))
    if r:
        sources = sorted(set(json.loads(r["sources_json"])) | {source})
        conn.execute("UPDATE sites SET last_seen_at=?, sources_json=? WHERE domain=?", (at, db.dumps(sources), d))
    else:
        db.insert(conn, "sites", {"domain": d, "first_seen_at": at, "last_seen_at": at, "sources_json": db.dumps([source])})
    return d


def batch_summary(conn: sqlite3.Connection, service: str, b: dict) -> None:
    at = now_iso()
    count = b.get("keyword_count", b.get("item_count", b.get("site_count")))
    conn.execute(
        "INSERT INTO gefei_batches (service, batch_id, finished_at, item_count, page_url, summary_json, first_seen_at,"
        " last_seen_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(service, batch_id) DO UPDATE SET"
        " finished_at=excluded.finished_at, item_count=excluded.item_count, page_url=excluded.page_url,"
        " summary_json=excluded.summary_json, last_seen_at=excluded.last_seen_at",
        (service, str(b["id"]), b.get("finished_at"), count, b.get("page_url"), db.dumps(b), at, at))


def keyword_batch(conn: sqlite3.Connection, batch_id: str, data: dict, call_id: int) -> list[str]:
    """Returns the keyword keys whose snapshot changed (new or updated)."""
    changed = []
    at = now_iso()
    if data.get("batch"):
        batch_summary(conn, "keywords", data["batch"])
    for kw in data.get("keywords") or []:
        key = touch_keyword(conn, kw.get("keyword", ""), kw.get("slug") or slug_from_url(kw.get("page_url")),
                            kw.get("category"))
        if not key:
            continue
        h = db.sha(kw)
        if not _changed(conn, "keyword_snapshots", "keyword=? AND batch_id=?", (key, batch_id), h):
            continue
        db.insert(conn, "keyword_snapshots", {
            "keyword": key, "batch_id": batch_id, "call_id": call_id, "captured_at": at,
            **{f: kw.get(f) for f in KEYWORD_FIELDS}, "data_json": db.dumps(kw), "row_hash": h})
        changed.append(key)
    return changed


def keyword_detail(conn: sqlite3.Connection, keyword: str, data: dict, call_id: int) -> None:
    word = data.get("word") or {}
    key = touch_keyword(conn, word.get("keyword") or keyword, word.get("slug"), word.get("category"))
    h = db.sha(data)
    if _changed(conn, "keyword_details", "keyword=?", (key,), h):
        db.insert(conn, "keyword_details", {"keyword": key, "call_id": call_id, "captured_at": now_iso(),
                                            "data_json": db.dumps(data), "row_hash": h})
    for rel in ("children", "parents", "synonyms"):
        for r in data.get(rel) or []:
            if r.get("keyword"):
                touch_keyword(conn, r["keyword"], r.get("slug"))


def launch_batch(conn: sqlite3.Connection, batch_id: str, data: dict, call_id: int) -> int:
    n = 0
    at = now_iso()
    if data.get("batch"):
        batch_summary(conn, "launches", data["batch"])
    for it in data.get("items") or []:
        item_key = it.get("source_url") or it.get("url") or db.sha(it)[:16]
        domain = touch_site(conn, it.get("domain") or it.get("url") or "", "launches")
        if it.get("keyword"):
            touch_keyword(conn, it["keyword"])
        h = db.sha(it)
        if not _changed(conn, "launches", "batch_id=? AND item_key=?", (batch_id, item_key), h):
            continue
        db.insert(conn, "launches", {
            "batch_id": batch_id, "item_key": item_key, "call_id": call_id, "captured_at": at,
            "source": it.get("source"), "title": it.get("title"), "url": it.get("url"), "domain": domain or None,
            "posted_at": it.get("posted_at"), "category": it.get("category"), "purpose": it.get("purpose"),
            "audience": it.get("audience"), "motive_type": it.get("motive_type"), "keyword": it.get("keyword"),
            "monetization": it.get("monetization"), "monthly_traffic": it.get("monthly_traffic"),
            "domain_registered": it.get("domain_registered"), "data_json": db.dumps(it), "row_hash": h})
        n += 1
    return n


def hosted_batch(conn: sqlite3.Connection, batch_id: str, period: str, data: dict, call_id: int) -> int:
    n = 0
    at = now_iso()
    if data.get("batch"):
        batch_summary(conn, "hosted", data["batch"])
    for s in data.get("sites") or []:
        site = touch_site(conn, s.get("site", ""), "hosted") or s.get("site", "")
        h = db.sha(s)
        if _changed(conn, "hosted_site_snapshots", "batch_id=? AND period=? AND site=?", (batch_id, period, site), h):
            db.insert(conn, "hosted_site_snapshots", {
                "batch_id": batch_id, "period": period, "site": site, "call_id": call_id, "captured_at": at,
                "platform": s.get("platform"), "title": s.get("title"), "description": s.get("description"),
                "peak_clicks": s.get("peak_clicks"), "latest28_clicks": s.get("latest28_clicks"),
                "data_json": db.dumps(s), "row_hash": h})
            n += 1
    for k in data.get("keywords") or []:
        key = touch_keyword(conn, k.get("keyword", ""))
        if not key:
            continue
        h = db.sha(k)
        if _changed(conn, "hosted_keyword_snapshots", "batch_id=? AND period=? AND keyword=?", (batch_id, period, key), h):
            db.insert(conn, "hosted_keyword_snapshots", {
                "batch_id": batch_id, "period": period, "keyword": key, "call_id": call_id, "captured_at": at,
                "site_count": k.get("site_count"), "peak_clicks": k.get("peak_clicks"),
                "latest28_clicks": k.get("latest28_clicks"), "data_json": db.dumps(k), "row_hash": h})
            n += 1
    return n


def revenue_month(conn: sqlite3.Connection, month: dict) -> None:
    conn.execute(
        "INSERT INTO revenue_months (month, has_monthly, dates_28d_json, last_seen_at) VALUES (?,?,?,?)"
        " ON CONFLICT(month) DO UPDATE SET has_monthly=excluded.has_monthly, dates_28d_json=excluded.dates_28d_json,"
        " last_seen_at=excluded.last_seen_at",
        (month["month"], 1 if month.get("has_monthly") else 0, db.dumps(month.get("dates_28d") or []), now_iso()))


def revenue_page(conn: sqlite3.Connection, month: str, period: str, data: dict, call_id: int, first_page: bool) -> int:
    n = 0
    at = now_iso()
    if first_page:  # channels repeat on every page and are report totals
        for c in data.get("channels") or []:
            h = db.sha(c)
            if _changed(conn, "revenue_channel_snapshots", "month=? AND period=? AND host IS ? AND channel IS ?"
                        " AND direction IS ?", (month, period, c.get("host"), c.get("channel"), c.get("direction")), h):
                db.insert(conn, "revenue_channel_snapshots", {
                    "month": month, "period": period, "host": c.get("host"), "channel": c.get("channel"),
                    "direction": c.get("direction"), "call_id": call_id, "captured_at": at,
                    "data_json": db.dumps(c), "row_hash": h})
    for s in data.get("sites") or []:
        domain = touch_site(conn, s.get("domain", ""), "revenue") or s.get("domain", "")
        h = db.sha(s)
        if _changed(conn, "revenue_site_snapshots", "month=? AND period=? AND domain=?", (month, period, domain), h):
            db.insert(conn, "revenue_site_snapshots", {
                "month": month, "period": period, "domain": domain, "call_id": call_id, "captured_at": at,
                "global_rank": s.get("global_rank"), "category": s.get("category"),
                "data_json": db.dumps(s), "row_hash": h})
            n += 1
    return n
