from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from radar import db
from radar.config import Paths, Settings

FIX = Path(__file__).resolve().parent / "fixtures"
DAY1 = date(2026, 11, 13)


def ok(data, charged=0, rid="req_" + "a" * 32):
    return {"ok": True, "requestId": rid, "credits": {"charged": charged}, "data": data, "meta": {}}


class FakeGefei:
    """In-memory Ge Fei: the real catalog fixtures plus scripted data services."""

    def __init__(self):
        self.tools = json.loads((FIX / "gefei-tools.json").read_text(encoding="utf-8"))
        self.openapi = json.loads((FIX / "gefei-openapi.json").read_text(encoding="utf-8"))
        self.calls: list[tuple[str, str, dict, dict | None]] = []
        self.kw_batches = [
            {"id": "kb2", "finished_at": "2026-11-12T10:00:00+08:00", "keyword_count": 2, "page_url": "u"},
            {"id": "kb1", "finished_at": "2026-10-01T10:00:00+08:00", "keyword_count": 1, "page_url": "u"},
        ]
        self.kw_page_size = 1
        self.kw_detail = {
            "kb2": [
                {"keyword": "AI Baby Dance", "category": "AI video", "kind": "new", "trend_now": "up",
                 "heat_ratio": 1.5, "growth_pct": 80, "appear_date": "2026-11-10", "burst_date": None,
                 "pushed_on": "2026-11-12", "page_count": 3, "targeted_count": 1, "verdict": "worth it",
                 "verdict_reasons": [], "verdict_suggestion": "build a page", "brief": {"what": "baby dance video"},
                 "sources": ["google"], "spark": [1, 2, 3], "page_url": "https://new.web.cafe/word/ai-baby-dance"},
                {"keyword": "mortgage calculator", "category": "finance", "kind": "old", "trend_now": "",
                 "heat_ratio": 0.2, "growth_pct": 1, "appear_date": None, "burst_date": None, "pushed_on": None,
                 "page_count": 0, "targeted_count": 0, "verdict": "", "verdict_reasons": [],
                 "verdict_suggestion": "", "brief": None, "sources": [], "spark": [], "page_url": None},
            ],
            "kb1": [{"keyword": "ai pet boxing", "category": "AI video", "kind": "spike", "trend_now": "",
                     "heat_ratio": 0.8, "growth_pct": 20, "appear_date": None, "burst_date": None, "pushed_on": None,
                     "page_count": 0, "targeted_count": 0, "verdict": "", "verdict_reasons": [],
                     "verdict_suggestion": "", "brief": None, "sources": [], "spark": [],
                     "page_url": "https://new.web.cafe/word/ai-pet-boxing"}],
        }
        self.launch_batches = [{"id": "lb1", "finished_at": "2026-11-12T09:00:00+08:00", "item_count": 2}]
        self.launch_items = {"lb1": [
            {"source": "hn", "source_url": "https://news/1", "title": "BabyDance AI - photo to dancing video",
             "url": "https://babydance.ai", "domain": "babydance.ai", "purpose": "AI video generator",
             "category": "AI video", "keyword": "ai baby dance", "monetization": "subscription"},
            {"source": "hn", "source_url": "https://news/2", "title": "Tax helper", "url": "https://tax.example",
             "domain": "tax.example", "purpose": "taxes", "category": "finance", "keyword": None}]}
        self.hosted_batches = [{"id": "hb1", "finished_at": "2026-11-11T09:00:00+08:00", "site_count": 1,
                                "keyword_count": 1}]
        self.hosted = {"sites": [{"site": "dancefx.app", "platform": "vercel", "title": "DanceFX AI dance effects",
                                  "description": "ai dance filter", "latest28_clicks": 1200, "peak_clicks": 1500}],
                       "keywords": [{"keyword": "ai dance filter", "latest28_clicks": 900, "site_count": 2}],
                       "reports_28d": [{"platform": "vercel", "date_28d": "2026-11-01"}]}
        self.months = [{"month": "2026-11", "has_monthly": False, "dates_28d": ["2026-11-05"]},
                       {"month": "2026-10", "has_monthly": True, "dates_28d": []}]
        self.revenue_pages = 2
        self.locked: set[str] = set()
        self.fail_once: set[str] = set()
        self.query: dict[str, dict] = {"keyword_volume": {"rows": [{"keyword": "ai baby dance", "volume": 12100}]}}
        self.balance: float | None = 500  # credits.balance on /api/v1/me (None = not reported)
        self.reject_token = False  # every authenticated call answers 401
        self.offline = False  # the network is down

    def __call__(self, method, url, headers, body):
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        payload = json.loads(body) if body else None
        self.calls.append((method, u.path, q, payload))
        if self.offline:
            raise OSError("[Errno 8] nodename nor servname provided")
        if self.reject_token and u.path not in ("/api/v1/tools", "/api/openapi.json"):
            return 401, {}, json.dumps({"ok": False, "code": "auth", "error": "invalid token",
                                        "requestId": "req_" + "d" * 32}).encode()
        if u.path == "/api/v1/me":
            credits = {"charged": 0} if self.balance is None else {"charged": 0, "balance": self.balance}
            return 200, {}, json.dumps({"ok": True, "requestId": "req_" + "c" * 32, "credits": credits,
                                        "data": {"plan": "member"}}).encode()
        if u.path == "/api/v1/tools":
            return 200, {}, json.dumps(self.tools).encode()
        if u.path == "/api/openapi.json":
            return 200, {}, json.dumps(self.openapi).encode()
        if u.path in self.fail_once:
            self.fail_once.discard(u.path)
            return 503, {"Retry-After": "0"}, json.dumps({"ok": False, "code": "unavailable", "error": "x",
                                                          "requestId": "req_" + "f" * 32}).encode()
        if u.path in self.locked:
            return 403, {}, json.dumps({"ok": False, "code": "data_locked", "error": "locked",
                                        "requestId": "req_" + "e" * 32, "meta": {}}).encode()
        data = self.route(u.path, q, payload)
        if data is None:
            return 404, {}, json.dumps({"ok": False, "code": "not_found", "error": u.path}).encode()
        charged = 0 if u.path.startswith(("/api/v1/keywords", "/api/v1/launches", "/api/v1/hosted",
                                          "/api/v2/checkouts")) else 2
        return 200, {"X-Request-Id": "req_" + "b" * 32}, json.dumps(ok(data, charged)).encode()

    def route(self, path, q, payload):
        page = int(q.get("page", 1))
        if path == "/api/v1/keywords/batches":
            size = self.kw_page_size
            chunk = self.kw_batches[(page - 1) * size: page * size]
            return {"batches": chunk, "has_more": page * size < len(self.kw_batches)}
        if path.startswith("/api/v1/keywords/batches/"):
            bid = path.rsplit("/", 1)[1]
            b = next(x for x in self.kw_batches if x["id"] == bid)
            return {"batch": b, "keywords": self.kw_detail[bid]}
        if path.startswith("/api/v1/keywords/word/"):
            slug = path.rsplit("/", 1)[1]
            return {"word": {"keyword": slug.replace("-", " "), "slug": slug}, "children": [], "parents": [],
                    "synonyms": [{"keyword": "baby dance ai", "slug": "baby-dance-ai"}]}
        if path == "/api/v1/launches/batches":
            return {"batches": self.launch_batches, "has_more": False}
        if path.startswith("/api/v1/launches/batches/"):
            bid = path.rsplit("/", 1)[1]
            return {"batch": self.launch_batches[0], "items": self.launch_items[bid]}
        if path == "/api/v1/hosted/batches":
            return {"batches": self.hosted_batches, "has_more": False}
        if path.startswith("/api/v1/hosted/batches/"):
            d = dict(self.hosted)
            if "28d" in q:
                d = {**d, "date_28d": q["28d"], "reports": []}
                d["sites"] = [{**d["sites"][0], "latest28_clicks": 1100}]
            return d
        if path == "/api/v2/checkouts/months":
            return {"months": self.months, "has_more": False}
        if path.startswith("/api/v2/checkouts/months/"):
            return {"page": page, "page_size": 50, "has_more": page < self.revenue_pages,
                    "channels": [{"host": "stripe.com", "channel": "stripe", "direction": "out", "periods": {"x": 1}}],
                    "sites": [{"domain": f"site{page}.ai", "channels": [], "first_period": "2026-10",
                               "global_rank": 1000 * page, "category": "AI image", "traffic": [], "page_url": "p"}]}
        tool = path.rsplit("/", 1)[1]
        return self.query.get(tool)


class FakeLark:
    """lark-cli: the read-only preflight commands plus docs +create / +update."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.logged_in = True
        self.nodes = {"wikiDaily": "Daily reports", "wikiOpp": "Opportunities"}
        self.editable = {"wikiDaily", "wikiOpp"}
        self.fail = False  # publishing (create / update) fails
        self.installed = True
        self.created = 0

    def __call__(self, args, cwd):
        if not self.installed:
            raise FileNotFoundError(2, "No such file or directory", args[0])
        self.calls.append(args)
        sub = args[1:3]
        if args[1] == "--version":
            return 0, "lark-cli version 1.0.77\n", ""
        if sub == ["auth", "status"]:
            user = {"status": "ready", "available": True, "verified": True} if self.logged_in else \
                {"status": "missing", "available": False, "message": "User identity: missing"}
            return 0, json.dumps({"identities": {"user": user, "bot": {"status": "ready", "available": True}},
                                  "identity": "user"}), ""
        if sub == ["wiki", "+node-get"]:
            tok = args[args.index("--node-token") + 1]
            if tok not in self.nodes:
                return 0, json.dumps({"ok": False, "error": {"type": "api", "code": 131005, "message": "not found"}}), ""
            return 0, json.dumps({"ok": True, "data": {"node": {"node_token": tok, "title": self.nodes[tok]}}}), ""
        if sub == ["drive", "permission.members"]:
            tok = args[args.index("--token") + 1]
            return 0, json.dumps({"ok": True, "data": {"auth_result": tok in self.editable}}), ""
        if "--help" in args:
            return 0, "--parent-token --doc-format --content --doc --command overwrite", ""
        content = args[args.index("--content") + 1]
        assert content.startswith("@") and (cwd / content[1:]).is_file()
        if self.fail:
            return 1, "", "permission denied"
        if "+create" in args:
            self.created += 1
            doc = f"doc{self.created}"
            self.editable.add(doc)
            return 0, json.dumps({"ok": True, "data": {"document": {"document_id": doc,
                                                                    "url": f"https://x.feishu.cn/docx/{doc}"}}}), ""
        return 0, json.dumps({"ok": True, "data": {"document": {"revision_id": 2}}}), ""

    @property
    def publishes(self) -> list[list[str]]:
        return [a for a in self.calls if a[1] == "docs" and a[2] in ("+create", "+update") and "--help" not in a]


def which(name: str) -> str:
    return f"/usr/local/bin/{name}"


def browser_report(day: date = DAY1, **failed) -> dict:
    """The agent's preflight.browser.json with every check passing; name=dict(...) overrides one check."""
    from radar.preflight import BROWSER_CHECKS, watchlist_urls
    from radar.config import TZ
    urls = {"Browser connection": ["about:blank"], "Public web": ["https://en.wikipedia.org/wiki/Meme"],
            "TikTok": ["https://www.tiktok.com/tag/aibaby"], "CapCut": ["https://www.capcut.com/templates"],
            "Instagram": ["https://www.instagram.com/explore/tags/aibaby/"],
            "X": ["https://x.com/search?q=ai%20baby"], "YouTube": ["https://www.youtube.com/results?search_query=x"],
            "Creative Center": ["https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en"],
            "Watchlist": [v[0] for v in watchlist_urls().values()]}
    checks = []
    for n in BROWSER_CHECKS:
        c = {"name": n, "status": "pass", "access": "logged_in" if n in ("TikTok", "Instagram", "X") else "not_needed",
             "urls": urls[n], "result": f"{n} research page loaded with content"}
        c.update(failed.get(n.replace(" ", "_"), {}))
        checks.append(c)
    return {"day": day.isoformat(), "checked_at": datetime.combine(day, time(8), TZ).isoformat(),
            "browser": "Claude in Chrome", "checks": checks}


def ready(paths: Paths, day: date = DAY1, **failed) -> Path:
    """Write the agent's browser preflight report for `day`."""
    return write(paths.work(day) / "preflight.browser.json", browser_report(day, **failed))


def make_ctx(paths, conn, settings, fake, lk, day: date = DAY1, browser: bool = True, **kw):
    """A pipeline context living on `day`, with Lark configured and (by default) a passing browser report."""
    from radar import pipeline
    from radar.config import LarkSettings
    advance(day)
    settings.lark = LarkSettings(daily_parent="wikiDaily", opportunity_parent="wikiOpp")
    if browser:
        ready(paths, day)
    return pipeline.Context(day=day, settings=settings, paths=paths, conn=conn, transport=fake, lark_runner=lk,
                            which=kw.pop("which", which), say=kw.pop("say", lambda s: None), **kw)


class Clock:
    """A fake wall clock: starts at 18:00 on a day (after fixture collection times) and ticks 1s per reading."""

    def __init__(self):
        self.day(DAY1)

    def day(self, d: date, hour: int = 18) -> None:
        from radar.config import TZ
        self.t = datetime.combine(d, time(hour), TZ)

    def advance_to(self, d: date) -> None:
        if self.t.date() < d:
            self.day(d)

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


def advance(d: date) -> None:
    """Simulate living on research day `d`: move the fake clock forward to it (never back)."""
    from radar import config
    config._clock.advance_to(d)


@pytest.fixture(autouse=True)
def clock():
    """Every test runs on a controlled clock (DAY1 18:00 by default); move it with clock.day(D)."""
    from radar import config
    c = Clock()
    config.set_clock(c)
    yield c
    config.set_clock(None)


@pytest.fixture
def fake() -> FakeGefei:
    return FakeGefei()


@pytest.fixture
def paths(tmp_path, monkeypatch) -> Paths:
    monkeypatch.setenv("AMR_CONFIG_DIR", str(tmp_path / "no-config"))
    monkeypatch.delenv("GEFEI_API_TOKEN", raising=False)
    p = Paths(tmp_path / "data")
    p.ensure()
    return p


@pytest.fixture
def conn(paths):
    c = db.connect(paths.db)
    yield c
    c.close()


@pytest.fixture
def settings() -> Settings:
    s = Settings()
    s.gefei.token = "wc_mcp_test"
    return s


def coverage(**status) -> list[dict]:
    """Full social coverage; pass platform=("failed", "reason") to change one."""
    from radar.config import COVERAGE_SOURCES
    out = []
    for p in COVERAGE_SOURCES:
        st, note = status.get(p.replace(" ", "_"), ("covered", ""))
        out.append({"platform": p, "status": st, "window": "" if st in ("failed", "not_attempted") else "last 48h",
                    "signals": "found" if st == "covered" else "unknown", "note": note})
    return out


def research_doc(day: date = DAY1, **over) -> dict:
    doc = {
        "day": day.isoformat(),
        "trends": [{"id": "ai-baby-dance", "name": "AI Baby Dance", "summary": "babies dancing, AI-made",
                    "aliases": ["baby dance ai"], "search_terms": ["ai baby dance"], "regions": ["US"],
                    "platforms": ["TikTok"]}],
        "formats": [{"id": "photo-to-dance", "name": "Photo to dance video", "user_input": "one photo",
                     "output": "5s dancing clip"}],
        "opportunities": [{"id": "baby-dance-template", "name": "Baby Dance AI Template", "product_type": "video",
                           "search_terms": ["ai baby dance"]}],
        "links": [{"from": "trend:ai-baby-dance", "to": "format:photo-to-dance", "relation": "uses"},
                  {"from": "format:photo-to-dance", "to": "opportunity:baby-dance-template", "relation": "enables"},
                  {"from": "trend:ai-baby-dance", "to": "keyword:AI Baby Dance", "relation": "searched_as"}],
        "evidence": [
            {"ref": "e1", "entity": "trend:ai-baby-dance", "channel": "social", "source": "TikTok",
             "url": "https://tiktok.com/tag/aibabydance", "metric": "posts_24h", "value": 100, "unit": "posts",
             "region": "US", "sample_size": 100, "metric_definition": "new posts in 24h under the hashtag",
             "collected_at": f"{day.isoformat()}T09:00:00+08:00", "confidence": "medium", "tag": "已核实"},
            {"ref": "e2", "entity": "opportunity:baby-dance-template", "channel": "search", "source": "keyword_volume",
             "metric": "search_volume", "value": 1000, "unit": "searches/mo", "region": "US",
             "metric_definition": "Google Ads monthly average", "collected_at": f"{day.isoformat()}T09:30:00+08:00",
             "confidence": "medium", "tag": "第三方读数"},
        ],
        "gaps": [{"source": "Instagram", "note": "login wall"}],
        "social_coverage": coverage(),
        "notes": "sweep done",
    }
    doc.update(over)
    return doc


def assessment(entity: str, **over) -> dict:
    a = {
        "entity": entity, "lifecycle": "emerging", "decision": "monitor", "priority": "P2", "confidence": "medium",
        "dimensions": {d: {"level": "medium", "note": f"{d} note", "evidence": []}
                       for d in ("social_momentum", "search_demand", "audience_participation", "template_potential",
                                 "ai_feasibility", "competition", "timing")},
        "summary": f"{entity} summary", "rationale": f"{entity} rationale", "why_now": "now",
        "assumptions": ["assumed"], "open_questions": ["q?"], "next_steps": [],
        "tracked": {"kind": "evidence", "metric": "posts_24h", "region": "US"},
    }
    a.update(over)
    return a


DEEP = {s: f"{s} text" for s in ("trend_overview", "why_now", "social_evidence", "search_demand",
                                 "audience_behavior", "format_analysis", "product_opportunity", "competition",
                                 "ai_feasibility", "recommendation", "evidence_confidence", "remaining_questions")}


def write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path
