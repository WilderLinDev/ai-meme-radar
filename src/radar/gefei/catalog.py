"""The callable Ge Fei API catalog, read live from the service.

`/api/v1/tools` and `/api/openapi.json` are the only authority. Every tool in
either document becomes callable; nothing is hand-listed here. Operations that
appear only in the OpenAPI document (account endpoints, legacy aliases) are
added with group `account` or `openapi`.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from .. import db
from ..config import now_iso

TOOLS_PATH = "/api/v1/tools"
OPENAPI_PATH = "/api/openapi.json"
MAX_AGE = timedelta(hours=20)
_PARAM = re.compile(r"\{([^}]+)\}")


@dataclass(frozen=True)
class Tool:
    id: str
    group: str
    title: str
    method: str
    path: str
    price_label: str
    params: dict
    required: tuple[str, ...]

    @property
    def path_params(self) -> list[str]:
        return _PARAM.findall(self.path)

    @property
    def charges_credits(self) -> bool:
        return self.group not in ("data", "account")

    def build(self, params: dict) -> tuple[str, str, dict, dict | None]:
        """-> (method, path, query, json_body). Raises ValueError on missing/unknown params."""
        missing = [p for p in (*self.required, *self.path_params) if params.get(p) in (None, "", [])]
        if missing:
            raise ValueError(f"{self.id}: missing required params {missing}")
        known = set(self.params) | set(self.path_params)
        unknown = sorted(set(params) - known) if known else []
        if unknown:
            raise ValueError(f"{self.id}: unknown params {unknown}; known: {sorted(known)}")
        path = self.path
        rest = dict(params)
        for name in self.path_params:
            path = path.replace("{" + name + "}", str(rest.pop(name)))
        if self.method == "GET":
            return "GET", path, {k: v for k, v in rest.items() if v is not None}, None
        return self.method, path, {}, rest


def _from_tools_doc(doc: dict) -> list[Tool]:
    out = []
    for t in doc.get("tools", []):
        endpoint = str(t.get("endpoint", ""))
        method, _, url = endpoint.partition(" ") if " " in endpoint else (t.get("method") or "POST", "", endpoint)
        path = re.sub(r"^https?://[^/]+", "", url)
        out.append(Tool(
            id=t["id"], group=str(t.get("group", "")), title=str(t.get("title", "")),
            method=method.upper(), path=path, price_label=str((t.get("price") or {}).get("label", "")),
            params=t.get("params") or {}, required=tuple(t.get("required") or ()),
        ))
    return out


def _from_openapi(doc: dict, known_paths: set[tuple[str, str]], known_ids: set[str]) -> list[Tool]:
    out = []
    for path, ops in (doc.get("paths") or {}).items():
        for method, op in ops.items():
            if (method.upper(), path) in known_paths:
                continue
            ident = op.get("operationId") or (method + "_" + re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_"))
            if ident in known_ids:
                continue
            params, required = {}, []
            for p in op.get("parameters") or []:
                params[p["name"]] = {"type": (p.get("schema") or {}).get("type", "string"),
                                     "description": (p.get("schema") or {}).get("description", "")}
                if p.get("required") and p.get("in") != "path":
                    required.append(p["name"])
            body = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
            for name, spec in (body.get("properties") or {}).items():
                params[name] = spec
            required += list(body.get("required") or [])
            group = "account" if path in ("/api/v1/me", "/api/v1/usage") else "openapi"
            out.append(Tool(id=ident, group=group, title=str(op.get("summary", "")), method=method.upper(),
                            path=path, price_label="", params=params, required=tuple(required)))
    return out


def parse(tools_doc: dict, openapi_doc: dict) -> list[Tool]:
    tools = _from_tools_doc(tools_doc)
    extra = _from_openapi(openapi_doc, {(t.method, t.path) for t in tools}, {t.id for t in tools})
    return tools + extra


def store(conn: sqlite3.Connection, tools_doc: dict, openapi_doc: dict) -> list[Tool]:
    tools = parse(tools_doc, openapi_doc)
    listed = {t.id for t in _from_tools_doc(tools_doc)}
    digest = db.sha([tools_doc, openapi_doc])
    with db.tx(conn):
        cat_id = db.insert(conn, "api_catalog", {
            "fetched_at": now_iso(), "sha": digest, "tool_count": len(tools),
            "tools_json": db.dumps(tools_doc), "openapi_json": db.dumps(openapi_doc)})
        conn.execute("DELETE FROM api_tools")
        for t in tools:
            db.insert(conn, "api_tools", {
                "tool_id": t.id, "grp": t.group, "title": t.title, "method": t.method, "path": t.path,
                "price_label": t.price_label, "params_json": db.dumps(t.params),
                "required_json": db.dumps(list(t.required)),
                "source": "tools" if t.id in listed else "openapi", "catalog_id": cat_id})
    return tools


def load(conn: sqlite3.Connection) -> dict[str, Tool]:
    return {r["tool_id"]: Tool(id=r["tool_id"], group=r["grp"], title=r["title"], method=r["method"],
                               path=r["path"], price_label=r["price_label"],
                               params=json.loads(r["params_json"]), required=tuple(json.loads(r["required_json"])))
            for r in db.rows(conn, "SELECT * FROM api_tools")}


def is_fresh(conn: sqlite3.Connection) -> bool:
    r = db.one(conn, "SELECT fetched_at FROM api_catalog ORDER BY id DESC LIMIT 1")
    if not r:
        return False
    return datetime.now().astimezone() - datetime.fromisoformat(r["fetched_at"]) < MAX_AGE
