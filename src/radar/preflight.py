"""Strict preflight gate: every prerequisite of the daily run is checked before any stage starts.

The gate is binary. READY means every required check passed; anything failed or unverified is
NOT READY, and no stage (sync, discovery, research, assessment, backtest, reports, publishing)
starts. All independent checks run before the report is shown, so every problem arrives at once.

Python verifies what it can verify deterministically:
* local:   Python, dependencies, settings, environment overrides, project config files, data /
           report / work / feedback folders, disk space, SQLite schema and integrity, `uv`, the lock
* gefei:   token, endpoint and live catalog, authentication (`GET /api/v1/me`, which returns the
           balance when available), data-service access (free page-1 list calls)
* lark:    `lark-cli` runs, the configured identity is logged in (verified with the server), each
           destination Wiki node exists and grants edit, the create / update commands exist, and
           every document the run will overwrite still grants edit

The browser checks (connection, public web, every social platform, Creative Center, Watchlist
pages, login state) belong to the agent: it writes work/DAY/preflight.browser.json and Python
only validates that report. Python never claims to know a browser login state.

Nothing here spends research credits or writes to Lark.
"""
from __future__ import annotations

import csv
import importlib.metadata
import json
import os
import shutil
import sqlite3
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError

from . import db, lark
from .config import (ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_REPORTS_DIR, ENV_TOKEN, REPO, SOCIAL_PLATFORMS, TZ, Paths,
                     Settings, now, now_iso)
from .gefei.client import Client, GefeiError, Transport
from .gefei.sync import DETAIL_TOOL, LIST_TOOL

MIN_PYTHON = (3, 12)
MIN_FREE_MB = 200
BROWSER_FILE = "preflight.browser.json"
REPORT_FILE = "preflight.json"
BROWSER_CHECKS = ("Browser connection", "Public web", *SOCIAL_PLATFORMS, "Creative Center", "Watchlist")
PLATFORM_HOSTS = {"TikTok": ("tiktok.com",), "CapCut": ("capcut.com",), "Instagram": ("instagram.com",),
                  "X": ("x.com", "twitter.com"), "YouTube": ("youtube.com",),
                  "Creative Center": ("ads.tiktok.com",)}
OPTIONAL_BROWSER_ACCESS = {"Instagram", "X", "Watchlist"}
WATCHLIST_COLUMNS = ("platform", "handle", "profile_url", "selected")
REVENUE_TOOLS = ("income_months_v2", "income_month_v2")


@dataclass
class Check:
    area: str  # local | gefei | lark | browser
    name: str
    ok: bool
    result: str  # what was actually observed
    reason: str = ""  # why it failed (empty when ok)
    fix: str = ""  # what the user must do (empty when ok)
    blocking: bool = True


@dataclass
class Report:
    day: str
    checked_at: str
    checks: list[Check] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.blocking]

    @property
    def ready(self) -> bool:
        return bool(self.checks) and not self.failed

    def to_json(self) -> dict:
        return {"day": self.day, "checked_at": self.checked_at, "ready": self.ready,
                "failed": [c.name for c in self.failed], "checks": [asdict(c) for c in self.checks]}

    def render(self) -> str:
        head = (f"PREFLIGHT {self.day}: READY ({sum(c.ok for c in self.checks)} passed, "
                f"{sum(not c.ok and not c.blocking for c in self.checks)} warnings)" if self.ready else
                f"PREFLIGHT {self.day}: NOT READY ({len(self.failed)} of {len(self.checks)} checks failed)")
        lines = [head]
        for c in self.checks:
            label = 'PASS' if c.ok else 'FAILED' if c.blocking else 'WARN'
            lines.append(f"  [{label}] {c.area} / {c.name}: {c.result}")
            if not c.ok:
                lines += [f"           reason: {c.reason}", f"           fix:    {c.fix}"]
        if not self.ready:
            lines.append("No stage was started. Fix every FAILED item above, redo the browser checks that failed, "
                         "then run again: the gate rechecks everything and the full workflow starts by itself.")
        return "\n".join(lines)


def ok(area: str, name: str, result: str) -> Check:
    return Check(area, name, True, result)


def bad(area: str, name: str, result: str, reason: str, fix: str) -> Check:
    return Check(area, name, False, result, reason, fix)


# ---------------------------------------------------------------- local
def environment_checks(which: Callable[[str], str | None]) -> list[Check]:
    """Checks that need neither settings nor the database."""
    out = []
    v = sys.version_info
    py = f"{v.major}.{v.minor}.{v.micro}"
    out.append(ok("local", "Python", f"{py} (needs >= 3.12)") if (v.major, v.minor) >= MIN_PYTHON else
               bad("local", "Python", py, "Python 3.12 or newer is required", "run through `uv run` (uses .python-version)"))
    try:
        pv = importlib.metadata.version("pydantic")
        major = int(pv.split(".")[0])
        out.append(ok("local", "Dependencies", f"pydantic {pv}") if major >= 2 else
                   bad("local", "Dependencies", f"pydantic {pv}", "pydantic 2 is required", "run `uv sync --locked`"))
    except importlib.metadata.PackageNotFoundError:
        out.append(bad("local", "Dependencies", "pydantic not installed", "a required package is missing",
                       "run `uv sync --locked`"))
    uv = which("uv")
    out.append(ok("local", "uv executable", uv) if uv else
               bad("local", "uv executable", "not on PATH", "the workflow is run with `uv run`",
                   "install uv (https://docs.astral.sh/uv/) and make sure it is on PATH"))
    out.append(_research_config())
    out.append(_watchlist_config())
    return out


def _research_config() -> Check:
    path = REPO / "config" / "research.toml"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        return bad("local", "Research vocabulary", str(path), f"cannot read: {type(e).__name__}",
                   "restore config/research.toml from git")
    terms = raw.get("creative_terms")
    if not isinstance(terms, list) or not terms:
        return bad("local", "Research vocabulary", str(path), "creative_terms is missing or empty",
                   "restore config/research.toml from git")
    lists = sum(1 for x in raw.values() if isinstance(x, list))
    return ok("local", "Research vocabulary", f"{lists} term lists, {len(terms)} creative terms")


def watchlist_urls() -> dict[str, list[str]]:
    """Selected Watchlist profile URLs by platform (config/watchlist.csv)."""
    out: dict[str, list[str]] = {}
    with open(REPO / "config" / "watchlist.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("selected") or "").strip() == "yes":
                out.setdefault(r["platform"].strip(), []).append(r["profile_url"].strip())
    return out


def _watchlist_config() -> Check:
    path = REPO / "config" / "watchlist.csv"
    try:
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
            header = rows[0].keys() if rows else []
    except OSError as e:
        return bad("local", "Watchlist", str(path), f"cannot read: {type(e).__name__}", "restore config/watchlist.csv")
    missing = [c for c in WATCHLIST_COLUMNS if c not in header]
    if missing:
        return bad("local", "Watchlist", str(path), f"missing columns {missing}", "restore config/watchlist.csv")
    selected = [r for r in rows if (r["selected"] or "").strip() == "yes"]
    problems = [f"row {i + 2}" for i, r in enumerate(rows) if (r["selected"] or "").strip() == "yes" and (
        r["platform"] not in SOCIAL_PLATFORMS or urlparse(r["profile_url"]).scheme != "https")]
    if not selected or problems:
        return bad("local", "Watchlist", f"{len(selected)} selected accounts",
                   "no selected account" if not selected else f"bad platform or profile_url in {problems[:5]}",
                   "fix config/watchlist.csv (platform from the fixed list, https profile_url, selected=yes)")
    plats = sorted({r["platform"] for r in selected})
    return ok("local", "Watchlist", f"{len(selected)} selected accounts on {', '.join(plats)}")


def settings_checks(settings: Settings, env: dict) -> list[Check]:
    src = str(settings.source) if settings.source else "none (defaults)"
    overrides = [n for n in (ENV_TOKEN, ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_REPORTS_DIR) if (env.get(n) or "").strip()]
    out = [ok("local", "Settings", f"parsed {src}; environment overrides: {', '.join(overrides) or 'none'}")]
    rel = [n for n in (ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_REPORTS_DIR)
           if (env.get(n) or "").strip() and not Path(env[n].strip()).expanduser().is_absolute()]
    if rel:
        out.append(bad("local", "Environment variables", ", ".join(rel), "folder overrides must be absolute paths",
                       f"set {', '.join(rel)} to absolute paths"))
    else:
        out.append(ok("local", "Environment variables", "folder overrides are absolute (or unset)"))
    if settings.gefei.keyword_detail_limit < 0 or settings.gefei.refresh_days < 0:
        out.append(bad("local", "Ge Fei settings", "negative value", "keyword_detail_limit and "
                       "refresh_days must be >= 0", "fix [gefei] in settings.toml"))
    elif urlparse(settings.gefei.base_url).scheme != "https":
        out.append(bad("local", "Ge Fei settings", settings.gefei.base_url, "base_url must be https",
                       "fix [gefei] base_url in settings.toml"))
    else:
        out.append(ok("local", "Ge Fei settings", f"base_url {settings.gefei.base_url}"))
    return out


def folder_checks(paths: Paths, day: date) -> list[Check]:
    out = []
    folders = [("Data folder", paths.root), ("Daily report folder", paths.reports / "daily"),
               ("Opportunity report folder", paths.reports / "opportunities"),
               ("Work folder", paths.work(day)), ("Feedback inbox", paths.feedback_inbox)]
    for name, p in folders:
        probe = p / ".preflight-probe"
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            out.append(ok("local", name, f"{p} is writable"))
        except OSError as e:
            out.append(bad("local", name, str(p), f"not writable: {type(e).__name__}: {e.strerror or e}",
                           f"make {p} writable, or point the folder elsewhere ({ENV_DATA_DIR} / {ENV_REPORTS_DIR})"))
    try:
        free = shutil.disk_usage(paths.root).free // (1024 * 1024)
        out.append(ok("local", "Disk space", f"{free} MB free") if free >= MIN_FREE_MB else
                   bad("local", "Disk space", f"{free} MB free", f"less than {MIN_FREE_MB} MB free",
                       f"free disk space on the volume holding {paths.root}"))
    except OSError as e:
        out.append(bad("local", "Disk space", str(paths.root), f"cannot read: {e}", f"check {paths.root}"))
    out.append(_feedback_files(paths.feedback_inbox))
    return out


def _feedback_files(inbox: Path) -> Check:
    from .research.ingest import InputError, load_model
    from .research.models import FeedbackFile
    files = sorted(inbox.glob("*.json")) if inbox.is_dir() else []
    problems = []
    for p in files:
        try:
            load_model(p, FeedbackFile)
        except InputError as e:
            problems += e.problems[:3]
    if problems:
        return bad("local", "Feedback files", f"{len(files)} files", "; ".join(problems[:5]),
                   f"fix or remove the invalid files in {inbox}")
    return ok("local", "Feedback files", f"{len(files)} files parse")


def database_checks(conn: sqlite3.Connection, path: Path) -> list[Check]:
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
    except sqlite3.Error as e:
        return [bad("local", "SQLite database", str(path), f"{type(e).__name__}: {e}",
                    f"close other programs using {path}; if it is damaged, move it aside")]
    if version != db.SCHEMA_VERSION:
        return [bad("local", "SQLite database", f"schema {version}", f"this code needs schema {db.SCHEMA_VERSION}",
                    f"move {path} aside (there are no migrations)")]
    if integrity != "ok":
        return [bad("local", "SQLite database", str(path), f"integrity check: {integrity}",
                    f"move {path} aside and start a fresh store")]
    return [ok("local", "SQLite database", f"{path}: schema {version}, integrity ok, writable")]


# ---------------------------------------------------------------- Ge Fei
def required_tools(services: tuple[str, ...]) -> set[str]:
    need = {"me"}
    for s in services:
        need |= set(REVENUE_TOOLS) if s == "revenue" else {LIST_TOOL[s], DETAIL_TOOL[s]}
    if "keywords" in services:
        need.add("keyword_detail")
    return need


def gefei_checks(settings: Settings, conn: sqlite3.Connection, transport: Transport, day: date,
                 services: tuple[str, ...]) -> list[Check]:
    out: list[Check] = []
    token = settings.token
    names = ("Ge Fei endpoint and catalog", "Ge Fei authentication", "Ge Fei credits", "Ge Fei data services")
    if not token:
        out.append(bad("gefei", "Ge Fei token", "not set", "the token is required for sync and every query API",
                       f"put the wc_mcp_… token from https://seo.web.cafe/api/ in ${ENV_TOKEN} or [gefei] token "
                       "of settings.toml (never in chat or the repo)"))
    elif not token.startswith("wc_mcp_"):
        out.append(bad("gefei", "Ge Fei token", f"set (from {settings.token_from}), wrong format",
                       "Ge Fei tokens start with wc_mcp_", "copy the API token again from https://seo.web.cafe/api/"))
    else:
        out.append(ok("gefei", "Ge Fei token", f"set (from {settings.token_from})"))
    client = Client(conn, token, settings.gefei.base_url, transport, day, max_retries=1)
    try:
        tools = client.refresh_catalog(force=True)
        missing = sorted(required_tools(services) - set(tools))
        out.append(bad("gefei", names[0], f"{len(tools)} tools", f"catalog lacks {missing}",
                       "the API changed; update the client before running") if missing else
                   ok("gefei", names[0], f"{settings.gefei.base_url} reachable, {len(tools)} tools in the live catalog"))
        catalog_ok = not missing
    except (GefeiError, OSError, ValueError) as e:
        out.append(bad("gefei", names[0], settings.gefei.base_url, settings.redact(f"unreachable: {e}"),
                       "check the network / proxy and that https://seo.web.cafe/api/ opens"))
        catalog_ok = False
    if not (catalog_ok and out[0].ok):
        why = "the token is missing or malformed" if not out[0].ok else "the endpoint or catalog check failed"
        return out + [bad("gefei", n, "not verified", why, "fix the failed Ge Fei check above") for n in (names[1], names[3])]

    try:
        me = client.call("me", {}, purpose="preflight", max_age=timedelta(0))
        out.append(ok("gefei", names[1], f"token accepted (request {me.request_id or '-'})"))
    except GefeiError as e:
        if e.status == 401 or e.code == "auth":
            out.append(bad("gefei", names[1], f"HTTP {e.status} {e.code}", "the token was rejected",
                           "create a new token at https://seo.web.cafe/api/ and update it locally"))
        else:
            out.append(bad("gefei", names[1], f"HTTP {e.status} {e.code}", settings.redact(str(e)),
                           "retry later; if it persists, check the account at https://seo.web.cafe/api/"))
        return out + [bad("gefei", names[3], "not verified", "authentication failed", "fix Ge Fei authentication")]
    credits = me.body.get("credits")
    balance = credits.get("balance") if isinstance(credits, dict) else None
    if type(balance) not in (int, float):
        balance = me.body.get("apiAvailable")
    if type(balance) not in (int, float) and isinstance(me.data, dict):
        balance = me.data.get("apiAvailable")
    if type(balance) in (int, float) and balance > 0:
        out.append(ok("gefei", names[2], f"API credits available: {balance:g}"))
    else:
        reading = f"API credits available: {balance:g}" if type(balance) in (int, float) else "API balance not reported"
        out.append(Check("gefei", names[2], False, reading,
                         "paid query balance is exhausted or unverified",
                         "continue with data services and public evidence; skip paid queries", blocking=False))

    locked = []
    for s in services:
        tool = "income_months_v2" if s == "revenue" else LIST_TOOL[s]
        try:
            client.call(tool, {"page": 1}, purpose="preflight", max_age=timedelta(0))
        except GefeiError as e:
            locked.append(f"{s}: HTTP {e.status} {e.code}")
    out.append(bad("gefei", names[3], "; ".join(locked), "a data service is locked or unavailable",
                   "unlock the data service at https://new.web.cafe/data with this account") if locked else
               ok("gefei", names[3], f"{', '.join(services)} list endpoints answered (free calls)"))
    return out


# ---------------------------------------------------------------- Lark
def _lark(runner: lark.Runner, args: list[str], cwd: Path) -> tuple[bool, dict, str]:
    try:
        code, stdout, stderr = runner(args, cwd)
    except Exception as e:  # noqa: BLE001 - missing binary, subprocess.TimeoutExpired: all mean "not usable"
        return False, {}, f"{type(e).__name__}: {e}"
    doc: dict = {}
    text = stdout or ""
    if "{" in text:
        try:
            doc = json.loads(text[text.index("{"):])
        except json.JSONDecodeError:
            doc = {}
    good = code == 0 and doc.get("ok", True) is not False
    err = ""
    if not good:
        e = doc.get("error")
        err = (e.get("message") if isinstance(e, dict) else str(e or "")) or (stderr or stdout or f"exit {code}")
        err = err.strip()[:300]
    return good, doc, err


def _can_edit(runner: lark.Runner, s, token: str, kind: str, cwd: Path) -> tuple[bool, str]:
    good, doc, err = _lark(runner, [s.cli, "drive", "permission.members", "auth", "--token", token, "--type", kind,
                                    "--action", "edit", "--as", s.identity, "--format", "json"], cwd)
    if not good:
        return False, err or "permission check failed"
    data = doc.get("data") if isinstance(doc.get("data"), dict) else doc
    return data.get("auth_result") is True, "" if data.get("auth_result") is True else "no edit permission"


def lark_checks(settings: Settings, conn: sqlite3.Connection, runner: lark.Runner,
                which: Callable[[str], str | None], cwd: Path) -> list[Check]:
    """Each check runs when what it depends on passed; otherwise it is reported as not verified."""
    s = settings.lark
    out: list[Check] = []

    def unverified(name: str, why: str) -> Check:
        return bad("lark", name, "not verified", why, "fix the failed Lark check it depends on")

    exe = which(s.cli)
    good, _, err = _lark(runner, [s.cli, "--version"], cwd) if exe else (False, {}, "")
    cli_ok = bool(exe) and good
    out.append(ok("lark", "lark-cli executable", exe) if cli_ok else
               bad("lark", "lark-cli executable", exe or "not on PATH", err or f"{s.cli} not found",
                   "install lark-cli and make sure it is on PATH (or set [lark] cli)"))
    ident_ok = s.identity in ("user", "bot")
    conf = ([] if s.daily_parent else ["[lark] daily_parent is empty"]) + \
        ([] if ident_ok else [f"[lark] identity must be user or bot, not {s.identity!r}"])
    out.append(bad("lark", "Lark settings", "; ".join(conf), "publishing is a required delivery step",
                   "set [lark] daily_parent (a Wiki node token) and identity in settings.toml") if conf else
               ok("lark", "Lark settings", f"identity {s.identity}, daily_parent set, opportunity_parent "
                                           f"{'set' if s.opportunity_parent else '= daily_parent'}"))

    auth_ok = False
    if not (cli_ok and ident_ok):
        out.append(unverified("Lark authentication", "needs a working lark-cli and a valid identity"))
    else:
        good, doc, err = _lark(runner, [s.cli, "auth", "status", "--json", "--verify"], cwd)
        ident = ((doc.get("identities") or {}).get(s.identity) or {}) if good else {}
        auth_ok = good and bool(ident.get("available")) and ident.get("verified") is not False
        if auth_ok:
            out.append(ok("lark", "Lark authentication", f"identity {s.identity} logged in and verified with the server"))
        else:
            fix = "run `lark-cli auth login` in a terminal and finish the browser login" if s.identity == "user" \
                else "configure the lark-cli app (bot) with `lark-cli config` / `lark-cli doctor`"
            out.append(bad("lark", "Lark authentication", f"identity {s.identity}: {ident.get('status') or 'unavailable'}",
                           err or ident.get("message") or f"{s.identity} identity is not logged in", fix))

    seen: dict[str, Check] = {}
    for name, token in (("Lark daily destination", s.daily_parent),
                        ("Lark opportunity destination", s.opportunity_parent or s.daily_parent)):
        if not (auth_ok and token):
            out.append(unverified(name, "needs Lark authentication and [lark] daily_parent"))
        elif token in seen:
            prev = seen[token]
            out.append(Check("lark", name, prev.ok, f"same node as daily: {prev.result}", prev.reason, prev.fix))
        else:
            seen[token] = _destination(runner, s, name, token, cwd)
            out.append(seen[token])

    if not cli_ok:
        out.append(unverified("Lark document commands", "needs a working lark-cli"))
    else:
        missing = [f"docs {sub}" for sub, flags in (("+create", ("--parent-token", "--doc-format", "--content")),
                                                     ("+update", ("--doc", "--command", "--content")))
                   if any(f not in _help_text(runner, [s.cli, "docs", sub, "--help"], cwd) for f in flags)]
        out.append(bad("lark", "Lark document commands", ", ".join(missing),
                       "this lark-cli lacks a command the publisher uses", "run `lark-cli update`") if missing else
                   ok("lark", "Lark document commands", "docs +create and docs +update (overwrite) are available"))

    if not auth_ok:
        out.append(unverified("Lark existing documents", "needs Lark authentication"))
    else:
        to_update = [(k, d["doc_id"]) for k, _ in lark.pending(conn)
                     for d in [db.one(conn, "SELECT doc_id FROM lark_docs WHERE doc_key=?", (k,))] if d and d["doc_id"]]
        denied = [f"{k} ({why})" for k, doc_id in to_update
                  for can, why in [_can_edit(runner, s, doc_id, "docx", cwd)] if not can]
        out.append(bad("lark", "Lark existing documents", f"{len(denied)} of {len(to_update)} documents",
                       "; ".join(denied[:5]), f"restore {s.identity}'s edit access to those documents") if denied else
                   ok("lark", "Lark existing documents", f"{len(to_update)} documents due for update are editable"
                      if to_update else "no existing document is due for update"))
    return out


def _destination(runner: lark.Runner, s, name: str, token: str, cwd: Path) -> Check:
    good, doc, err = _lark(runner, [s.cli, "wiki", "+node-get", "--node-token", token, "--as", s.identity,
                                    "--format", "json"], cwd)
    if not good:
        return bad("lark", name, f"node {token}", err or "not found",
                   "use the token of an existing Wiki node this identity can open (a Drive folder cannot be checked "
                   "for edit rights read-only, so destinations must be Wiki nodes)")
    data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
    title = (data.get("node") or data).get("title") or token
    can, why = _can_edit(runner, s, token, "wiki", cwd)
    return ok("lark", name, f"Wiki node “{title}” exists, {s.identity} can edit") if can else \
        bad("lark", name, f"Wiki node “{title}” exists", why, f"give the {s.identity} identity edit access to it")


def _help_text(runner: lark.Runner, args: list[str], cwd: Path) -> str:
    try:
        code, stdout, stderr = runner(args, cwd)
    except Exception:  # noqa: BLE001 - a missing or broken CLI simply has no commands
        return ""
    return (stdout or "") + (stderr or "") if code == 0 else ""


# ---------------------------------------------------------------- browser (agent-reported)
class BrowserCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    status: Literal["pass", "failed"]
    access: Literal["logged_in", "not_needed", "login_required", "blocked", "unreachable"]
    urls: list[str] = []  # the research pages actually opened (not just a homepage)
    result: str  # what the agent saw
    reason: str = ""
    fix: str = ""


class BrowserReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: date
    checked_at: datetime
    browser: str  # the browser integration used
    checks: list[BrowserCheck]


def _host_ok(url: str, hosts: tuple[str, ...]) -> bool:
    h = (urlparse(url).hostname or "").lower()
    return any(h == x or h.endswith("." + x) for x in hosts)


def _deep(url: str) -> bool:
    u = urlparse(url)
    return u.scheme in ("http", "https") and bool(u.hostname) and u.path.strip("/") != ""


def browser_checks(path: Path, day: date) -> list[Check]:
    fix_all = (f"have the agent run every browser check and write {path} "
               "(see .agents/skills/ai-meme-radar/SKILL.md, Preflight)")
    if not path.is_file():
        return [bad("browser", n, "not verified", f"{path.name} is missing", fix_all) for n in BROWSER_CHECKS]
    try:
        rep = BrowserReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        why = f"{path.name} is invalid: {str(e).splitlines()[0][:200]}"
        return [bad("browser", n, "not verified", why, fix_all) for n in BROWSER_CHECKS]
    at = rep.checked_at.astimezone(TZ) if rep.checked_at.tzinfo else rep.checked_at.replace(tzinfo=TZ)
    if rep.day != day or at.date() != day or at > now() + timedelta(minutes=5):
        why = f"report is for {rep.day}, checked {at.isoformat(timespec='minutes')}; it must be from today ({day})"
        return [bad("browser", n, "stale", why, fix_all) for n in BROWSER_CHECKS]
    by_name: dict[str, BrowserCheck] = {}
    for c in rep.checks:
        by_name.setdefault(c.name, c)
    try:
        watch = watchlist_urls()
    except OSError:
        watch = {}
    out = []
    for n in BROWSER_CHECKS:
        c = by_name.get(n)
        if c is None:
            out.append(bad("browser", n, "not verified", f"{path.name} has no '{n}' check", fix_all))
            continue
        seen = f"{c.result} [{rep.browser}; access {c.access}; opened {', '.join(c.urls) or 'nothing'}]"
        if c.status == "failed":
            if n in OPTIONAL_BROWSER_ACCESS or (n in SOCIAL_PLATFORMS and c.access == "login_required"):
                out.append(Check("browser", n, False, seen, c.reason or "source unavailable",
                                 "use available public pages and record a research gap", blocking=False))
            else:
                out.append(bad("browser", n, seen, c.reason or "the agent reported a failure",
                               c.fix or ("log in to Creative Center in the connected browser"
                                         if n == "Creative Center" and c.access == "login_required"
                                         else "make the page reachable in the connected browser")))
            continue
        problem = _pass_problem(n, c, watch)
        out.append(bad("browser", n, seen, problem, fix_all) if problem else ok("browser", n, seen))
    return out


def _pass_problem(name: str, c: BrowserCheck, watch: dict[str, list[str]]) -> str:
    """Why a check marked pass does not hold up, or ''."""
    if c.access not in ("logged_in", "not_needed"):
        return f"marked pass with access {c.access}"
    if not c.result.strip():
        return "marked pass without saying what was verified"
    if name == "Browser connection":
        return "" if c.urls else "no page was opened"
    if not c.urls or not all(_deep(u) for u in c.urls):
        return "pass needs research pages actually opened (a URL with a path, not a homepage)"
    if name in PLATFORM_HOSTS and not any(_host_ok(u, PLATFORM_HOSTS[name]) for u in c.urls):
        return f"no opened page is on {' / '.join(PLATFORM_HOSTS[name])}"
    if name == "Watchlist":
        norm = {u.rstrip("/").lower() for u in c.urls}
        missing = [p for p, urls in watch.items() if not norm & {u.rstrip("/").lower() for u in urls}]
        if missing:
            return f"no selected Watchlist profile opened for {', '.join(sorted(missing))}"
    return ""


# ---------------------------------------------------------------- the gate
def run_checks(ctx, env: dict | None = None) -> Report:
    """Every check, independent ones all run; `ctx` is a pipeline.Context."""
    env = dict(os.environ) if env is None else env
    rep = Report(ctx.day.isoformat(), now_iso())
    rep.checks += environment_checks(ctx.which)
    rep.checks += settings_checks(ctx.settings, env)
    rep.checks += folder_checks(ctx.paths, ctx.day)
    rep.checks += database_checks(ctx.conn, ctx.paths.db)
    rep.checks.append(ok("local", "Single run", f"run lock {ctx.paths.lock} held by this process (pid {os.getpid()})"))
    rep.checks += gefei_checks(ctx.settings, ctx.conn, ctx.transport, ctx.day, ctx.services)
    rep.checks += lark_checks(ctx.settings, ctx.conn, ctx.lark_runner, ctx.which, ctx.paths.root)
    rep.checks += browser_checks(ctx.work / BROWSER_FILE, ctx.day)
    for c in rep.checks:
        c.result, c.reason = ctx.settings.redact(c.result), ctx.settings.redact(c.reason)
    return rep


def startup_failure(day: date, area_name: str, error: str, which: Callable[[str], str | None] = shutil.which) -> Report:
    """The report when settings or the database cannot even be opened: what can be checked is."""
    rep = Report(day.isoformat(), now_iso())
    rep.checks += environment_checks(which)
    rep.checks.append(bad("local", area_name, "cannot open", error,
                          "fix it as the reason says (settings.toml / environment, or move the old radar.db aside)"))
    rep.checks.append(bad("local", "Remaining checks", "not verified",
                          "Ge Fei, Lark, folders, database and browser checks need valid settings and database",
                          "fix the item above, then run again"))
    return rep
