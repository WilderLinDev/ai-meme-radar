"""Synchronize Ge Fei data services into SQLite, resumably.

Four services: emerging keywords, new-site launches, website discovery
(hosted), revenue (checkout referrals). Each unit of work (one batch detail,
one 28d snapshot, one revenue report) is a row in `sync_items`; a unit marked
`done` is never fetched again unless it is inside the refresh window, so the
first run pulls everything accessible and later runs only pull what is new or
may have changed. A failed unit stays `failed` and is retried next run.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .. import db
from ..config import TZ, Settings, now_iso, research_terms
from ..text import Vocabulary
from . import normalize
from .client import Client, GefeiError

SERVICES = ("keywords", "launches", "hosted", "revenue")
LIST_TOOL = {"keywords": "keyword_batches", "launches": "launch_batches", "hosted": "hosted_batches"}
DETAIL_TOOL = {"keywords": "keyword_batch", "launches": "launch_batch", "hosted": "hosted_batch"}
FATAL = {"auth", "account_required", "account_unavailable"}
SKIPPABLE = {"data_locked", "batch_not_found", "report_not_found", "report_28d_not_found",
             "batch_members_unavailable", "batch_reports_unavailable"}


@dataclass
class SyncReport:
    fetched: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    locked: list[str] = field(default_factory=list)
    new_keywords: list[str] = field(default_factory=list)
    new_batches: dict[str, list[str]] = field(default_factory=dict)

    def bump(self, kind: str, n: int = 1, *, skipped: bool = False) -> None:
        d = self.skipped if skipped else self.fetched
        d[kind] = d.get(kind, 0) + n


class Syncer:
    def __init__(self, conn: sqlite3.Connection, client: Client, settings: Settings, now: datetime | None = None):
        self.conn, self.client, self.settings = conn, client, settings
        self.now = now or datetime.now(TZ)
        self.report = SyncReport()
        terms = research_terms()
        self.vocab = Vocabulary(terms.get("creative_terms", []))

    # ---- checkpoint helpers ----
    def _item(self, kind: str, key: str) -> dict | None:
        return db.one(self.conn, "SELECT * FROM sync_items WHERE kind=? AND item_key=?", (kind, key))

    def _mark(self, kind: str, key: str, status: str, *, remote_at: str | None = None,
              call_id: int | None = None, error: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO sync_items (kind, item_key, status, attempts, remote_at, last_call_id, last_error, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(kind, item_key) DO UPDATE SET status=excluded.status,"
            " attempts=sync_items.attempts + excluded.attempts, remote_at=COALESCE(excluded.remote_at, sync_items.remote_at),"
            " last_call_id=COALESCE(excluded.last_call_id, sync_items.last_call_id), last_error=excluded.last_error,"
            " updated_at=excluded.updated_at",
            (kind, key, status, 0 if status == "done" else 1, remote_at, call_id, error, now_iso()))

    def _recent(self, finished_at: str | None) -> bool:
        if not finished_at:
            return True
        try:
            t = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        if t.tzinfo is None:
            t = t.replace(tzinfo=TZ)
        return self.now - t <= timedelta(days=self.settings.gefei.refresh_days)

    def _needs(self, kind: str, key: str, refreshable: bool) -> bool:
        it = self._item(kind, key)
        if it is None or it["status"] in ("pending", "failed"):
            return True
        if it["status"] == "locked":
            return False
        if refreshable:
            # refresh at most once per run day
            return it["updated_at"][:10] < self.now.date().isoformat()
        return False

    def _fetch(self, kind: str, key: str, tool: str, params: dict) -> object | None:
        """One unit. Returns data, or None when skipped (locked / missing). Raises on fatal errors."""
        try:
            res = self.client.call(tool, params, purpose=f"sync:{kind}")
        except GefeiError as e:
            if e.code in FATAL or e.status == 401:
                self._mark(kind, key, "failed", call_id=e.call_id, error=str(e))
                raise
            if e.code in SKIPPABLE or e.status in (403, 404):
                self._mark(kind, key, "locked", call_id=e.call_id, error=str(e))
                self.report.locked.append(f"{kind}:{key} ({e.code})")
                return None
            self._mark(kind, key, "failed", call_id=e.call_id, error=str(e))
            self.report.failed.append(f"{kind}:{key}: {e}")
            return None
        self._last_call = res.call_id
        return res.data

    # ---- batch services ----
    def _list_batches(self, service: str) -> list[dict]:
        """Walk list pages newest-first; stop once a whole page is already known and settled."""
        out, page = [], 1
        while True:
            data = self._fetch(f"{service}_list", f"page{page}", LIST_TOOL[service], {"page": page})
            if data is None:
                break
            self._mark(f"{service}_list", f"page{page}", "done", call_id=self._last_call)
            batches = data.get("batches") or []
            settled = 0
            for b in batches:
                normalize.batch_summary(self.conn, service, b)
                out.append(b)
                it = self._item(f"{service}_batch", str(b["id"]))
                if it and it["status"] in ("done", "locked") and not self._recent(b.get("finished_at")):
                    settled += 1
            if not data.get("has_more") or (batches and settled == len(batches)):
                break
            page += 1
        return out

    def sync_batches(self, service: str) -> None:
        kind = f"{service}_batch"
        for b in self._list_batches(service):
            bid = str(b["id"])
            is_new = self._item(kind, bid) is None
            if not self._needs(kind, bid, self._recent(b.get("finished_at"))):
                self.report.bump(kind, skipped=True)
                continue
            data = self._fetch(kind, bid, DETAIL_TOOL[service], {"id": bid})
            if data is None:
                continue
            call_id = self._last_call
            with db.tx(self.conn):
                if service == "keywords":
                    self.report.new_keywords += normalize.keyword_batch(self.conn, bid, data, call_id)
                elif service == "launches":
                    normalize.launch_batch(self.conn, bid, data, call_id)
                else:
                    normalize.hosted_batch(self.conn, bid, "default", data, call_id)
                self._mark(kind, bid, "done", remote_at=b.get("finished_at"), call_id=call_id)
            self.report.bump(kind)
            if is_new:
                self.report.new_batches.setdefault(service, []).append(bid)
            if service == "hosted":
                self._hosted_28d(bid, data)

    def _hosted_28d(self, bid: str, data: dict) -> None:
        dates = sorted({r.get("date_28d") for r in data.get("reports_28d") or [] if r.get("date_28d")})
        for d in dates:
            key = f"{bid}|{d}"
            if not self._needs("hosted_28d", key, False):
                self.report.bump("hosted_28d", skipped=True)
                continue
            snap = self._fetch("hosted_28d", key, "hosted_batch", {"id": bid, "28d": d})
            if snap is None:
                continue
            with db.tx(self.conn):
                normalize.hosted_batch(self.conn, bid, d, snap, self._last_call)
                self._mark("hosted_28d", key, "done", remote_at=d, call_id=self._last_call)
            self.report.bump("hosted_28d")

    # ---- revenue ----
    def sync_revenue(self) -> None:
        months, page = [], 1
        while True:
            data = self._fetch("revenue_list", f"page{page}", "income_months_v2", {"page": page})
            if data is None:
                break
            self._mark("revenue_list", f"page{page}", "done", call_id=self._last_call)
            for m in data.get("months") or []:
                normalize.revenue_month(self.conn, m)
                months.append(m)
            if not data.get("has_more"):
                break
            page += 1
        this_month = self.now.strftime("%Y-%m")
        prev_month = (self.now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        for m in months:
            month = m["month"]
            if m.get("has_monthly"):
                self._revenue_report(month, "monthly", None, refreshable=month in (this_month, prev_month))
            for d in m.get("dates_28d") or []:
                self._revenue_report(month, d, d, refreshable=False)

    def _revenue_report(self, month: str, period: str, date_28d: str | None, refreshable: bool) -> None:
        key = f"{month}|{period}"
        if not self._needs("revenue_report", key, refreshable):
            self.report.bump("revenue_report", skipped=True)
            return
        page, call_ids = 1, []
        pages: list[tuple[int, dict]] = []
        while True:
            params = {"month": month, "page": page}
            if date_28d:
                params["28d"] = date_28d
            data = self._fetch("revenue_report", key, "income_month_v2", params)
            if data is None:
                return  # unit stays failed/locked; retried next run from page 1
            pages.append((self._last_call, data))
            call_ids.append(self._last_call)
            if not data.get("has_more"):
                break
            page += 1
        with db.tx(self.conn):
            for i, (cid, data) in enumerate(pages):
                normalize.revenue_page(self.conn, month, period, data, cid, first_page=i == 0)
            self._mark("revenue_report", key, "done", remote_at=date_28d or month, call_id=call_ids[-1])
        self.report.bump("revenue_report")

    # ---- keyword details for creative candidates ----
    def sync_keyword_details(self) -> None:
        limit = self.settings.gefei.keyword_detail_limit
        if limit <= 0:
            return
        cands = db.rows(self.conn,
                        "SELECT k.keyword, k.slug, k.display FROM keywords k WHERE k.slug IS NOT NULL AND k.slug != ''"
                        " AND EXISTS (SELECT 1 FROM keyword_snapshots s WHERE s.keyword = k.keyword)"
                        " AND NOT EXISTS (SELECT 1 FROM keyword_details d WHERE d.keyword = k.keyword)"
                        " ORDER BY k.last_seen_at DESC")
        done = 0
        for c in cands:
            if done >= limit:
                break
            if not self.vocab.hits(c["display"]):
                continue
            key = c["keyword"]
            if not self._needs("keyword_detail", key, False):
                continue
            data = self._fetch("keyword_detail", key, "keyword_detail", {"slug": c["slug"]})
            done += 1
            if data is None:
                continue
            with db.tx(self.conn):
                normalize.keyword_detail(self.conn, key, data, self._last_call)
                self._mark("keyword_detail", key, "done", call_id=self._last_call)
            self.report.bump("keyword_detail")

    def run(self, services: tuple[str, ...] = SERVICES) -> SyncReport:
        self.client.refresh_catalog()
        for s in services:
            if s == "revenue":
                self.sync_revenue()
            else:
                self.sync_batches(s)
        if "keywords" in services:
            self.sync_keyword_details()
        return self.report


def pending_units(conn: sqlite3.Connection) -> list[dict]:
    return db.rows(conn, "SELECT kind, item_key, status, attempts, last_error FROM sync_items"
                         " WHERE status IN ('pending','failed') ORDER BY kind, item_key")


def credits_spent(conn: sqlite3.Connection, day: date) -> float:
    r = db.one(conn, "SELECT COALESCE(SUM(credits_charged),0) AS c FROM api_calls WHERE run_day=?", (day.isoformat(),))
    return float(r["c"]) if r else 0.0
