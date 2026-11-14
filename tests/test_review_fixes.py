"""Regression tests for the post-rebuild review findings."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest

from radar import backtest, db, decisions, lark, pipeline
from radar.config import ConfigError, LarkSettings, Paths, Settings, load_settings, redact
from radar.gefei.client import Client, GefeiError
from radar.reports import daily, deep
from radar.reports.daily import tracked_move
from radar.research.discover import Matcher, group
from radar.research.ingest import InputError, ingest_research
from conftest import DAY1, DEEP, FakeLark, advance, assessment, make_ctx, research_doc, write


def ingest(conn, paths, doc, day=DAY1):
    advance(day)
    return ingest_research(conn, write(paths.work(day) / "research.json", doc), day)


def assess(conn, paths, items, day=DAY1):
    advance(day)
    return decisions.ingest_assessments(conn, write(paths.work(day) / "assessments.json",
                                                    {"day": day.isoformat(), "assessments": items}), day)


def obs(day: date, value: float, ref: str, **over) -> dict:
    base = dict(research_doc()["evidence"][0])
    return dict(base, ref=ref, value=value, collected_at=f"{day.isoformat()}T09:00:00+08:00", **over)


def only_evidence(day: date, evidence: list[dict]) -> dict:
    return research_doc(day=day, trends=[], formats=[], opportunities=[], links=[], gaps=[], evidence=evidence)


# ---- 1. backtest revisions ----
def test_superseded_revisions_never_count(conn, paths):
    ingest(conn, paths, research_doc())
    trend = "trend:ai-baby-dance"
    assess(conn, paths, [assessment(trend, lifecycle="emerging")])            # rev 1, expects rising
    backtest.evaluate(conn, DAY1)
    assess(conn, paths, [assessment(trend, lifecycle="fading")])              # rev 2, expects falling
    d2 = DAY1 + timedelta(days=1)
    ingest(conn, paths, only_evidence(d2, [obs(d2, 100, "r-d2")]), d2)
    assess(conn, paths, [assessment(trend, lifecycle="emerging", priority="P1")], d2)  # second day
    d3 = DAY1 + timedelta(days=3)
    assess(conn, paths, [assessment(trend, lifecycle="emerging", tracked=None)], d3)   # unscorable
    d8 = DAY1 + timedelta(days=7)
    ingest(conn, paths, only_evidence(d8, [obs(d8, 200, "r-d8")]), d8)

    # rev 1 got a stored result before rev 2 existed; force it to look scored to prove it is ignored
    backtest.evaluate(conn, d8)
    rev1 = db.one(conn, "SELECT id FROM assessments WHERE entity=? AND day=? AND revision=1", (trend, DAY1.isoformat()))
    conn.execute("INSERT OR REPLACE INTO backtest_results (system, assessment_id, horizon_days, series_json, outcome,"
                 " detail, evaluated_at, outcome_at) VALUES ('lifecycle', ?, 7, 'null', 'hit', 'old', 'x', ?)",
                 (rev1["id"], d8.isoformat()))

    official = backtest.official(conn, system="lifecycle", entity=trend)
    by_day = {r["assessed_day"]: r for r in official}
    assert set(by_day) == {DAY1.isoformat(), d2.isoformat(), d3.isoformat()}  # one row per day
    assert by_day[DAY1.isoformat()]["revision"] == 2
    assert by_day[DAY1.isoformat()]["outcome"] == "miss"      # fading expected falling; it doubled
    assert by_day[d2.isoformat()]["outcome"] == "pending"     # due d2+7
    assert by_day[d3.isoformat()]["outcome"] == "unscorable"
    s = backtest.summary(conn)["lifecycle"]
    assert s["scored"] == 1 and s["good"] == 0                # rev-1 "hit" not counted
    assert all(r["revision"] == 2 for r in backtest.resolved_on(conn, d8) if r["assessed_day"] == DAY1.isoformat())
    # history is kept
    assert db.one(conn, "SELECT COUNT(*) n FROM backtest_results WHERE assessment_id=?", (rev1["id"],))["n"] == 1
    assert db.one(conn, "SELECT COUNT(*) n FROM assessments WHERE entity=?", (trend,))["n"] == 4


def test_no_observation_after_window_becomes_no_data(conn, paths):
    ingest(conn, paths, research_doc())
    assess(conn, paths, [assessment("trend:ai-baby-dance")])
    backtest.evaluate(conn, DAY1 + timedelta(days=30))
    assert backtest.official(conn, system="lifecycle")[0]["outcome"] == "no_data"


# ---- 2. schema version ----
def test_schema_version_is_checked_not_overwritten(tmp_path):
    p = tmp_path / "radar.db"
    c = db.connect(p)
    assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    c.close()
    db.connect(p).close()  # same version reopens

    raw = sqlite3.connect(p)
    raw.execute("PRAGMA user_version=99")
    raw.close()
    with pytest.raises(db.SchemaError, match="schema version 99"):
        db.connect(p)
    raw = sqlite3.connect(p)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 99  # not silently re-stamped
    raw.close()

    other = tmp_path / "other.db"
    raw = sqlite3.connect(other)
    raw.execute("CREATE TABLE stuff (x)")
    raw.close()
    with pytest.raises(db.SchemaError, match="not a radar database"):
        db.connect(other)


# ---- 3. transitive grouping ----
def test_candidate_groups_merge_transitively_and_deterministically(conn):
    m = Matcher(conn)
    cands = [
        {"channel": "search", "keyword": "AI Baby Dance"},                       # k1
        {"channel": "product", "domain": "babydance.ai", "title": "BabyDance"},  # d1
        {"channel": "market", "domain": "other.ai"},                             # d2, alone
        {"channel": "product", "keyword": "ai baby dance", "domain": "babydance.ai", "title": "bridge"},  # k1+d1
        {"channel": "search", "keyword": "ai  baby-dance"},                      # k1 again (normalized)
    ]
    groups = group(cands, m)
    assert len(groups) == 2
    big = next(g for g in groups if len(g["items"]) == 4)
    assert set(big["keys"]) == {"kw|ai baby dance", "site|babydance.ai"}
    assert set(big["channels"]) == {"search", "product"}
    assert sorted(i.get("title", "") for i in big["items"]) == ["", "", "BabyDance", "bridge"]
    assert group(list(cands), m) == groups  # deterministic
    # the bridge arriving last still joins the two earlier groups
    assert len(group([cands[0], cands[1], cands[3]], m)) == 1


# ---- 4. tracked metric comparability ----
def test_tracked_move_needs_identical_measurement():
    ident = {"kind": "evidence", "source": "TikTok", "metric": "posts_24h", "unit": "posts",
             "definition": "new posts in 24h", "region": "US"}
    prev = {"value": 100.0, "at": "2026-11-13T09:00", "ident": ident}
    assert tracked_move(prev, {"value": 150.0, "at": "2026-11-14T09:00", "ident": dict(ident)})[0] == 0.5
    for key, val in (("source", "Google"), ("metric", "search_volume"), ("unit", "searches"),
                     ("definition", "monthly"), ("region", "GB")):
        ch, why = tracked_move(prev, {"value": 150.0, "at": "2026-11-14T09:00", "ident": {**ident, key: val}})
        assert ch is None and "口径" in why
    assert tracked_move(prev, {"value": 150.0, "at": "x", "ident": None}) == (None, "跟踪指标缺少口径信息，不计算变化")
    assert tracked_move(None, prev) == (None, "")


def test_daily_report_does_not_compare_different_metrics(conn, paths):
    ingest(conn, paths, research_doc())
    assess(conn, paths, [assessment("trend:ai-baby-dance")])
    daily.build(conn, DAY1, paths)
    d2 = DAY1 + timedelta(days=1)
    # day 2: the tracked series is now search volume from Google, 50x larger
    ingest(conn, paths, only_evidence(d2, [dict(research_doc()["evidence"][1], ref="sv", entity="trend:ai-baby-dance",
                                                collected_at=f"{d2.isoformat()}T09:00:00+08:00", value=5000)]), d2)
    assess(conn, paths, [assessment("trend:ai-baby-dance",
                                    tracked={"kind": "evidence", "metric": "search_volume", "region": "US"})], d2)
    daily.build(conn, d2, paths)
    text = paths.daily_report(d2).read_text(encoding="utf-8")
    assert "跟踪指标口径与上次不同，不计算变化" in text
    assert "+4900%" not in text and "→ 5,000" not in text

    # day 3: same series measured the same way -> a real change is reported
    d3 = d2 + timedelta(days=1)
    ingest(conn, paths, only_evidence(d3, [dict(research_doc()["evidence"][1], ref="sv3", entity="trend:ai-baby-dance",
                                                collected_at=f"{d3.isoformat()}T09:00:00+08:00", value=8000)]), d3)
    daily.build(conn, d3, paths)
    assert "5,000 → 8,000（+60%）" in paths.daily_report(d3).read_text(encoding="utf-8")


# ---- 5. unified link validation ----
def _feedback(paths, value, field="link_add", entity="trend:ai-baby-dance"):
    for f in paths.feedback_inbox.glob("*.json"):
        f.unlink()
    write(paths.feedback_inbox / "f.json", {"feedback": [
        {"entity": entity, "field": field, "value": value, "reason": "r", "author": "pm",
         "at": "2099-01-01T00:00:00+08:00"}]})


@pytest.mark.parametrize("value,entity,message", [
    ("enables->opportunity:baby-dance-template", "trend:ai-baby-dance", "not allowed"),     # wrong relation
    ("uses->trend:ai-baby-dance", "format:photo-to-dance", "not allowed"),                  # wrong direction
    ("uses->format:ai-baby-dance", "trend:ai-baby-dance", "is not defined"),                # missing target
    ("uses", "trend:ai-baby-dance", "relation->kind:id"),                                   # malformed
    ("related->trend:ai-baby-dance", "trend:ai-baby-dance", "itself"),
])
def test_feedback_links_use_research_rules(conn, paths, value, entity, message):
    ingest(conn, paths, research_doc())
    _feedback(paths, value, entity=entity)
    with pytest.raises(InputError, match=message):
        decisions.ingest_feedback(conn, paths.feedback_inbox, DAY1)


def test_valid_feedback_link_is_applied(conn, paths):
    ingest(conn, paths, research_doc())
    _feedback(paths, "drives->opportunity:baby-dance-template")
    assert decisions.ingest_feedback(conn, paths.feedback_inbox, DAY1)["applied"] == 1
    from radar.research.ingest import current_links
    assert ("trend:ai-baby-dance", "opportunity:baby-dance-template", "drives") in current_links(conn)


# ---- 6. Lark documents in status ----
def test_status_lists_every_lark_document_with_url(conn, paths):
    ingest(conn, paths, research_doc())
    assess(conn, paths, [assessment("opportunity:baby-dance-template", decision="build", priority="P0", deep=DEEP,
                                    next_steps=["go"], tracked=None)])
    daily.build(conn, DAY1, paths)
    deep.build(conn, DAY1, paths)
    calls = []

    def runner(args, cwd):
        calls.append(args)
        if "深度研究" in " ".join(args):
            return 1, "", "no permission on wiki node"
        return 0, json.dumps({"data": {"document": {"document_id": "d1", "url": "https://x.feishu.cn/docx/d1"}}}), ""
    lark.publish(conn, LarkSettings(daily_parent="w"), runner)
    docs = {d["type"]: d for d in lark.documents(conn)}
    assert docs["daily"]["status"] == "synced" and docs["daily"]["url"] == "https://x.feishu.cn/docx/d1"
    assert docs["opportunity"]["status"] == "failed" and "no permission" in docs["opportunity"]["error"]
    assert paths.daily_report(DAY1).is_file()  # local report unaffected

    out = []
    pipeline.status(conn, DAY1, out.append)
    text = "\n".join(out)
    assert "[daily] AI 创作机会日报 2026-11-13 | synced | https://x.feishu.cn/docx/d1" in text
    assert "[opportunity] 深度研究：Baby Dance AI Template | failed | - |" in text and "no permission" in text

    paths.daily_report(DAY1).write_text("changed", encoding="utf-8")
    conn.execute("UPDATE reports SET content_hash='new' WHERE kind='daily'")
    assert {d["type"]: d["status"] for d in lark.documents(conn)}["daily"] == "stale"


def test_publishing_cannot_be_switched_off(conn, paths, tmp_path):
    ingest(conn, paths, research_doc())
    assess(conn, paths, [assessment("trend:ai-baby-dance")])
    daily.build(conn, DAY1, paths)
    assert [d["status"] for d in lark.documents(conn)] == ["unpublished"]
    with pytest.raises(RuntimeError, match="daily_parent"):
        lark.publish(conn, LarkSettings(), lambda a, c: (0, "", ""))
    toml(tmp_path / "cfg", "[lark]\nenabled = false\n")
    with pytest.raises(ConfigError, match="required"):
        load_settings(env={"AMR_CONFIG_DIR": str(tmp_path / "cfg")})


# ---- 7. settings ----
def toml(dirpath, text):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "settings.toml").write_text(text, encoding="utf-8")


def test_settings_env_toml_precedence_and_defaults(tmp_path):
    cfg = tmp_path / "cfg"
    toml(cfg, '[gefei]\ntoken = "wc_mcp_fromtoml"\n[lark]\ndaily_parent = "node"\n'
              '[paths]\ndata_dir = "/toml/data"\nreports_dir = "/toml/reports"\n')
    s = load_settings(env={"AMR_CONFIG_DIR": str(cfg)})                       # custom config dir + TOML fallback
    assert s.token == "wc_mcp_fromtoml" and s.token_from == "toml" and s.lark.daily_parent == "node"
    assert Paths.resolve(s).db.as_posix() == "/toml/data/radar.db"
    assert Paths.resolve(s).daily_report(DAY1).as_posix() == "/toml/reports/daily/2026-11-13.md"

    s = load_settings(env={"AMR_CONFIG_DIR": str(cfg), "GEFEI_API_TOKEN": "wc_mcp_fromenv",
                           "AMR_DATA_DIR": "/env/data", "AMR_REPORTS_DIR": "/env/reports"})
    assert s.token == "wc_mcp_fromenv" and s.token_from == "env"              # env wins
    assert Paths.resolve(s).root.as_posix() == "/env/data"
    assert Paths.resolve(s).reports.as_posix() == "/env/reports"

    s = load_settings(env={"AMR_CONFIG_DIR": str(tmp_path / "none")})         # no file: safe defaults
    assert s.source is None and s.token == "" and not s.lark.daily_parent
    assert Paths.resolve(s).root.name == "ai-meme-radar-data"
    s = load_settings(env={"AMR_CONFIG_DIR": str(tmp_path / "none"), "GEFEI_API_TOKEN": "wc_mcp_e"})
    assert s.token == "wc_mcp_e"                                               # env alone is enough


def test_missing_token_and_bad_toml_are_clear_errors(tmp_path):
    s = load_settings(env={"AMR_CONFIG_DIR": str(tmp_path)})
    with pytest.raises(ConfigError, match="GEFEI_API_TOKEN"):
        s.require_token()
    toml(tmp_path / "bad", '[gefei]\ntoken = "wc_mcp_secretvalue"\nrefresh_days = "soon"\n')
    with pytest.raises(ConfigError) as e:
        load_settings(env={"AMR_CONFIG_DIR": str(tmp_path / "bad")})
    assert "secretvalue" not in str(e.value) and "settings.toml" in str(e.value)
    toml(tmp_path / "broken", "[gefei\n")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_settings(env={"AMR_CONFIG_DIR": str(tmp_path / "broken")})


def test_secrets_are_redacted_everywhere(conn, paths, fake):
    secret = "wc_mcp_SuperSecret123"
    s = Settings()
    s.gefei.token = secret
    assert secret not in repr(s)
    assert redact(f"Authorization: Bearer {secret}", secret) == "Authorization: Bearer ***"
    assert redact("token wc_mcp_abcDEF other") == "token wc_mcp_*** other"

    def echo(method, url, headers, body):  # a server that echoes the auth header in its error
        if url.endswith(("/api/v1/tools", "/api/openapi.json")):
            return fake(method, url, headers, body)
        return 401, {}, json.dumps({"ok": False, "code": "auth", "error": f"bad {headers['Authorization']}"}).encode()
    c = Client(conn, secret, "https://seo.web.cafe", echo, DAY1)
    c.refresh_catalog()
    with pytest.raises(GefeiError) as e:
        c.call("serp", {"q": "x"})
    assert secret not in str(e.value)
    stored = db.one(conn, "SELECT error, url, params_json FROM api_calls WHERE id=?", (e.value.call_id,))
    assert secret not in json.dumps(stored)

    said = []
    ctx = pipeline.Context(day=DAY1, settings=s, paths=paths, conn=conn, transport=echo, say=said.append,
                           lark_runner=lambda a, c: (0, "", ""))
    pipeline.run(ctx)
    logged = json.dumps(db.rows(conn, "SELECT * FROM run_events")) + json.dumps(db.rows(conn, "SELECT * FROM gaps"))
    assert secret not in logged and secret not in "\n".join(said)


# ---- 8. deep report evidence scope ----
def test_deep_report_evidence_covers_related_entities_only(conn, paths):
    doc = research_doc()
    doc["trends"].append({"id": "unrelated-trend", "name": "Unrelated Trend"})
    doc["links"] += [{"from": "trend:ai-baby-dance", "to": "site:babydance.ai", "relation": "competitor"},
                     {"from": "opportunity:baby-dance-template", "to": "keyword:baby dance template",
                      "relation": "targets"}]
    t = f"{DAY1.isoformat()}T10:00:00+08:00"
    common = {"channel": "search", "source": "S", "collected_at": t, "confidence": "low", "tag": "第三方读数"}
    doc["evidence"] += [
        {**common, "ref": "kw1", "entity": "keyword:baby dance template", "metric": "search_volume", "value": 880,
         "metric_definition": "monthly avg", "region": "US"},
        {**common, "ref": "site1", "entity": "site:babydance.ai", "channel": "market", "metric": "visits",
         "value": 4200, "metric_definition": "monthly visits estimate"},
        {**common, "ref": "fmt1", "entity": "format:photo-to-dance", "channel": "social", "note": "template exists"},
        {**common, "ref": "nope1", "entity": "trend:unrelated-trend", "metric": "posts", "value": 7,
         "metric_definition": "posts"},
    ]
    ingest(conn, paths, doc)
    assess(conn, paths, [assessment("opportunity:baby-dance-template", decision="build", priority="P0", deep=DEEP,
                                    next_steps=["go"], tracked=None)])
    deep.build(conn, DAY1, paths)
    text = paths.opportunity_report("baby-dance-template", DAY1).read_text(encoding="utf-8")
    for ref in ("| e1 |", "| e2 |", "| kw1 |", "| site1 |", "| fmt1 |"):
        assert ref in text
    assert "nope1" not in text and "Unrelated Trend" not in text
    assert "关键词·baby dance template" in text and "网站·babydance.ai" in text


# ---- 9. single-instance lock ----
def test_run_lock_blocks_overlap_and_releases(paths, conn, settings, fake):
    ctx = make_ctx(paths, conn, settings, fake, FakeLark())
    with pipeline.run_lock(paths.lock):
        assert pipeline.run(ctx) == pipeline.BUSY
        with pytest.raises(pipeline.Busy, match="pid"):
            with pipeline.run_lock(paths.lock):
                pass
    # a leftover lock file from a dead process is not a lock
    paths.lock.write_text("pid 999999 since long ago\n", encoding="utf-8")
    assert pipeline.run(ctx) == pipeline.WAITING
    # released after an exception inside the block
    with pytest.raises(RuntimeError):
        with pipeline.run_lock(paths.lock):
            raise RuntimeError("boom")
    with pipeline.run_lock(paths.lock):
        pass
    # read-only status does not need the lock
    with pipeline.run_lock(paths.lock):
        pipeline.status(conn, DAY1, lambda s: None)
