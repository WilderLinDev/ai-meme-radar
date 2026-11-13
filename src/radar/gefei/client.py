"""HTTP client for the Ge Fei SEO Toolkit API.

Every call is written to `api_calls` before and after it runs: tool, params,
URL, status, `requestId`, credits actually charged (`credits.charged` or the
`X-Credits-Charged` header), timestamps and the full JSON response. Identical
successful calls are reused from SQLite within `max_age` so research does not
pay twice for the same question.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from .. import db
from ..config import now_iso, today
from . import catalog

Transport = Callable[[str, str, dict, bytes | None], tuple[int, dict, bytes]]
DEFAULT_MAX_AGE = {"data": timedelta(0), "account": timedelta(0), "method": timedelta(days=30),
                   "composed": timedelta(days=7), "raw": timedelta(days=7)}
RETRY_STATUS = {429, 502, 503}
USER_AGENT = "ai-meme-radar/3 (+https://seo.web.cafe/api/)"  # the default Python-urllib agent is blocked


class GefeiError(RuntimeError):
    def __init__(self, tool: str, status: int | None, code: str, message: str, call_id: int, request_id: str = ""):
        super().__init__(f"{tool}: HTTP {status} {code} {message} (request {request_id or '-'}, call #{call_id})")
        self.tool, self.status, self.code, self.call_id, self.request_id = tool, status, code, call_id, request_id


@dataclass
class Result:
    call_id: int
    tool: str
    data: object
    body: dict
    request_id: str
    credits: float | None
    cached: bool


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()) if e.headers else {}, e.read() or b""


def _header(headers: dict, name: str) -> str:
    low = name.lower()
    return next((str(v) for k, v in headers.items() if k.lower() == low), "")


class Client:
    def __init__(self, conn: sqlite3.Connection, token: str, base_url: str,
                 transport: Transport = urllib_transport, run_day: date | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_retries: int = 3):
        self.conn, self.token, self.base = conn, token, base_url.rstrip("/")
        self.transport, self.sleep, self.max_retries = transport, sleep, max_retries
        self.run_day = (run_day or today()).isoformat()
        self._tools: dict[str, catalog.Tool] | None = None

    # ---- catalog ----
    def refresh_catalog(self, force: bool = False) -> dict[str, catalog.Tool]:
        if force or not catalog.is_fresh(self.conn):
            tools_doc = self._get_json(catalog.TOOLS_PATH)
            openapi_doc = self._get_json(catalog.OPENAPI_PATH)
            catalog.store(self.conn, tools_doc, openapi_doc)
        self._tools = catalog.load(self.conn)
        return self._tools

    @property
    def tools(self) -> dict[str, catalog.Tool]:
        if self._tools is None:
            self._tools = catalog.load(self.conn) or self.refresh_catalog()
        return self._tools

    def _get_json(self, path: str) -> dict:
        status, _, raw = self.transport("GET", self.base + path, {"Accept": "application/json"}, None)
        if status != 200:
            raise GefeiError(path, status, "catalog", raw[:200].decode("utf-8", "replace"), 0)
        return json.loads(raw)

    # ---- calls ----
    def cached(self, tool_id: str, params: dict, max_age: timedelta) -> Result | None:
        if max_age <= timedelta(0):
            return None
        key = db.sha([tool_id, params])
        r = db.one(self.conn, "SELECT * FROM api_calls WHERE params_key=? AND ok=1 ORDER BY id DESC LIMIT 1", (key,))
        if not r or datetime.now().astimezone() - datetime.fromisoformat(r["finished_at"]) > max_age:
            return None
        body = json.loads(r["response_json"])
        return Result(r["id"], tool_id, body.get("data"), body, r["request_id"] or "", 0.0, True)

    def call(self, tool_id: str, params: dict | None = None, *, purpose: str = "",
             max_age: timedelta | None = None) -> Result:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        tool = self.tools.get(tool_id)
        if tool is None:
            raise KeyError(f"unknown Ge Fei tool {tool_id!r}; the live catalog has {len(self.tools)} tools")
        hit = self.cached(tool_id, params, DEFAULT_MAX_AGE.get(tool.group, timedelta(0)) if max_age is None else max_age)
        if hit:
            return hit
        method, path, query, body = tool.build(params)
        url = self.base + path + ("?" + urllib.parse.urlencode(query, doseq=True) if query else "")
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        call_id = db.insert(self.conn, "api_calls", {
            "tool_id": tool_id, "method": method, "url": url, "params_json": db.dumps(params),
            "params_key": db.sha([tool_id, params]), "ok": 0, "started_at": now_iso(),
            "run_day": self.run_day, "purpose": purpose})
        attempt = 0
        while True:
            try:
                status, rh, raw = self.transport(method, url, headers, payload)
            except OSError as e:  # network failure: record and stop
                self._finish(call_id, None, {}, None, "network", str(e))
                raise GefeiError(tool_id, None, "network", str(e), call_id) from e
            parsed = _parse(raw)
            if status in RETRY_STATUS and attempt < self.max_retries:
                attempt += 1
                wait = _retry_after(rh, attempt)
                self.sleep(wait)
                continue
            break
        ok = status == 200 and bool(parsed.get("ok", True)) if isinstance(parsed, dict) else False
        code = "" if ok else str((parsed or {}).get("code", "") if isinstance(parsed, dict) else "")
        err = "" if ok else str((parsed or {}).get("error", "") if isinstance(parsed, dict) else raw[:300])
        self._finish(call_id, status, rh, parsed, code, err, ok=ok)
        rid = _request_id(parsed, rh)
        if not ok:
            raise GefeiError(tool_id, status, code or "http", err, call_id, rid)
        credits = _credits(parsed, rh)
        if tool.group == "method":
            db.insert(self.conn, "knowledge_docs", {
                "tool_id": tool_id, "query": db.dumps(params), "call_id": call_id,
                "captured_at": now_iso(), "content_json": db.dumps(parsed.get("data"))})
        return Result(call_id, tool_id, parsed.get("data"), parsed, rid, credits, False)

    def _finish(self, call_id: int, status, rh: dict, parsed, code: str, err: str, ok: bool = False) -> None:
        self.conn.execute(
            "UPDATE api_calls SET status_code=?, ok=?, request_id=?, credits_charged=?, error_code=?, error=?,"
            " response_json=?, finished_at=? WHERE id=?",
            (status, 1 if ok else 0, _request_id(parsed, rh) or None, _credits(parsed, rh), code or None,
             err or None, db.dumps(parsed) if parsed is not None else None, now_iso(), call_id))


def _parse(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "code": "non_json", "error": raw[:300].decode("utf-8", "replace")}


def _request_id(parsed, headers: dict) -> str:
    if isinstance(parsed, dict) and parsed.get("requestId"):
        return str(parsed["requestId"])
    return _header(headers, "X-Request-Id")


def _credits(parsed, headers: dict) -> float | None:
    if isinstance(parsed, dict) and isinstance(parsed.get("credits"), dict) and "charged" in parsed["credits"]:
        try:
            return float(parsed["credits"]["charged"])
        except (TypeError, ValueError):
            pass
    h = _header(headers, "X-Credits-Charged")
    try:
        return float(h) if h else None
    except ValueError:
        return None


def _retry_after(headers: dict, attempt: int) -> float:
    h = _header(headers, "Retry-After")
    try:
        return min(float(h), 120.0) if h else float(2 ** attempt)
    except ValueError:
        return float(2 ** attempt)
