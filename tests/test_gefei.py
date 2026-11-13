from __future__ import annotations

import json
from datetime import timedelta

import pytest

from radar import db
from radar.gefei import catalog
from radar.gefei.client import Client, GefeiError
from radar.gefei.sync import Syncer, pending_units
from conftest import FIX, DAY1


def client(conn, fake):
    return Client(conn, "wc_mcp_test", "https://seo.web.cafe", fake, DAY1, sleep=lambda s: None)


def test_catalog_covers_every_published_endpoint():
    tools_doc = json.loads((FIX / "gefei-tools.json").read_text(encoding="utf-8"))
    openapi = json.loads((FIX / "gefei-openapi.json").read_text(encoding="utf-8"))
    tools = {t.id: t for t in catalog.parse(tools_doc, openapi)}
    groups = {}
    for t in tools.values():
        groups[t.group] = groups.get(t.group, 0) + 1
    assert groups["data"] == 16 and groups["composed"] == 16 and groups["raw"] == 16 and groups["method"] == 4
    assert {"me", "usage"} <= set(tools)  # OpenAPI-only operations are callable too
    paths = {(t.method, t.path) for t in tools.values()}
    for p, ops in openapi["paths"].items():
        for m in ops:
            assert (m.upper(), p) in paths, f"{m} {p} missing from catalog"


def test_tool_build_fills_path_params_and_rejects_unknown():
    tools_doc = json.loads((FIX / "gefei-tools.json").read_text(encoding="utf-8"))
    tools = {t.id: t for t in catalog.parse(tools_doc, {})}
    method, path, query, body = tools["income_month_v2"].build({"month": "2026-10", "page": 2, "28d": "2026-10-05"})
    assert (method, path, query, body) == ("GET", "/api/v2/checkouts/months/2026-10", {"page": 2, "28d": "2026-10-05"}, None)
    method, path, query, body = tools["keyword_volume"].build({"keywords": ["a"], "gl": "us"})
    assert method == "POST" and body == {"keywords": ["a"], "gl": "us"} and query == {}
    with pytest.raises(ValueError, match="missing"):
        tools["keyword_volume"].build({"gl": "us"})
    with pytest.raises(ValueError, match="unknown"):
        tools["keyword_volume"].build({"keywords": ["a"], "bogus": 1})


def test_calls_are_recorded_and_reused(conn, fake):
    c = client(conn, fake)
    c.refresh_catalog()
    r1 = c.call("keyword_volume", {"keywords": ["ai baby dance"], "gl": "us"}, purpose="t")
    r2 = c.call("keyword_volume", {"keywords": ["ai baby dance"], "gl": "us"})
    assert not r1.cached and r2.cached and r1.call_id == r2.call_id
    row = db.one(conn, "SELECT * FROM api_calls WHERE id=?", (r1.call_id,))
    assert row["ok"] == 1 and row["credits_charged"] == 2 and row["request_id"].startswith("req_")
    assert json.loads(row["response_json"])["data"]["rows"][0]["volume"] == 12100
    assert json.loads(row["params_json"]) == {"gl": "us", "keywords": ["ai baby dance"]}
    r3 = c.call("keyword_volume", {"keywords": ["ai baby dance"], "gl": "us"}, max_age=timedelta(0))
    assert not r3.cached and r3.call_id != r1.call_id


def test_errors_are_recorded_and_retries_honour_retry_after(conn, fake):
    c = client(conn, fake)
    c.refresh_catalog()
    fake.fail_once.add("/api/v1/keyword_volume")
    r = c.call("keyword_volume", {"keywords": ["x"]}, max_age=timedelta(0))
    assert r.data is not None
    fake.locked.add("/api/v1/serp")
    with pytest.raises(GefeiError) as e:
        c.call("serp", {"q": "x"})
    row = db.one(conn, "SELECT * FROM api_calls WHERE id=?", (e.value.call_id,))
    assert row["ok"] == 0 and row["status_code"] == 403 and row["error_code"] == "data_locked"


def test_initial_sync_pulls_everything_then_incremental(conn, fake, settings):
    from datetime import datetime
    from radar.config import TZ
    now = datetime(2026, 11, 13, 9, 0, tzinfo=TZ)
    rep = Syncer(conn, client(conn, fake), settings, now=now).run()
    assert rep.fetched["keywords_batch"] == 2 and rep.fetched["launches_batch"] == 1
    assert rep.fetched["hosted_batch"] == 1 and rep.fetched["hosted_28d"] == 1
    assert rep.fetched["revenue_report"] == 2  # 2026-10 monthly + 2026-11-05 28d
    assert db.one(conn, "SELECT COUNT(*) n FROM revenue_site_snapshots")["n"] == 4  # 2 reports x 2 pages
    assert db.one(conn, "SELECT COUNT(*) n FROM keyword_snapshots")["n"] == 3
    assert db.one(conn, "SELECT slug FROM keywords WHERE keyword='ai baby dance'")["slug"] == "ai-baby-dance"
    assert db.one(conn, "SELECT COUNT(*) n FROM keyword_details")["n"] == 2  # creative keywords only
    assert db.one(conn, "SELECT COUNT(*) n FROM hosted_site_snapshots")["n"] == 2  # default + 28d

    # same day again: nothing settled is fetched twice
    fake.calls.clear()
    rep2 = Syncer(conn, client(conn, fake), settings, now=now).run()
    fetched_details = [p for m, p, q, b in fake.calls if "/batches/" in p or "/months/" in p]
    assert fetched_details == [] and sum(rep2.fetched.values()) == 0

    # next day: recent batch kb2 is refreshed, old kb1 is not; a new batch is pulled; unchanged rows add no snapshots
    fake.kw_batches.insert(0, {"id": "kb3", "finished_at": "2026-11-14T08:00:00+08:00", "keyword_count": 1})
    fake.kw_detail["kb3"] = [dict(fake.kw_detail["kb2"][0], heat_ratio=2.5)]
    fake.calls.clear()
    rep3 = Syncer(conn, client(conn, fake), settings, now=datetime(2026, 11, 14, 9, 0, tzinfo=TZ)).run(("keywords",))
    got = sorted(p.rsplit("/", 1)[1] for m, p, q, b in fake.calls if "/keywords/batches/" in p)
    assert got == ["kb2", "kb3"] and rep3.new_batches == {"keywords": ["kb3"]}
    assert db.one(conn, "SELECT COUNT(*) n FROM keyword_snapshots")["n"] == 4


def test_failed_units_resume_and_locked_units_are_recorded(conn, fake, settings):
    fake.locked.add("/api/v1/launches/batches/lb1")
    fake.revenue_pages = 1
    real = fake.route

    def flaky(path, q, payload):
        if path == "/api/v1/hosted/batches/hb1" and "28d" not in q and not getattr(flaky, "done", False):
            flaky.done = True
            return None  # 404 -> treated as locked/missing for that unit
        return real(path, q, payload)
    fake.route = flaky
    c = client(conn, fake)
    c.max_retries = 0
    fake.fail_once.add("/api/v1/keywords/batches/kb1")
    rep = Syncer(conn, c, settings).run()
    assert any("lb1" in x for x in rep.locked)
    assert [u["item_key"] for u in pending_units(conn)] == ["kb1"]
    rep2 = Syncer(conn, c, settings).run(("keywords",))
    assert rep2.fetched.get("keywords_batch", 0) >= 1 and pending_units(conn) == []
