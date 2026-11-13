"""Regression tests: discovery limits and exploration, evidence refs and fingerprints, as-of reports,
social coverage."""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

import pytest

from radar import backtest, db, decisions
from radar.gefei import normalize
from radar.reports import daily, deep
from radar.research import discover as disc
from radar.research.ingest import InputError, current_links, ingest_research
from conftest import DAY1, DEEP, assessment, coverage, research_doc, write

D2, D8 = DAY1 + timedelta(days=1), DAY1 + timedelta(days=7)
SINCE = "2000-01-01"


def ingest(conn, paths, doc, day=DAY1):
    return ingest_research(conn, write(paths.work(day) / f"research-{len(list(paths.work(day).glob('*')))}.json",
                                       doc), day)


def only(day, **over):
    """A research file adding only what `over` gives (no entities)."""
    return research_doc(day=day, **({"trends": [], "formats": [], "opportunities": [], "links": [], "evidence": [],
                                     "gaps": []} | over))


def snap(conn, keyword, kind, heat, growth, batch="b1", category="", brief=None):
    normalize.keyword_batch(conn, batch, {"keywords": [{"keyword": keyword, "kind": kind, "heat_ratio": heat,
                                                        "growth_pct": growth, "category": category,
                                                        "brief": brief}]}, 1)


# ---- 1. discovery ----
def test_launches_cannot_starve_hosted_and_counts_are_recorded(conn, monkeypatch):
    monkeypatch.setattr(disc, "PER_SOURCE", 3)
    for i in range(6):
        normalize.launch_batch(conn, "lb", {"items": [{"source": "hn", "source_url": f"s{i}", "title": f"AI video {i}",
                                                       "url": f"https://l{i}.ai", "domain": f"l{i}.ai",
                                                       "posted_at": f"2026-11-1{i}"}]}, 1)
    normalize.hosted_batch(conn, "hb", "default", {"sites": [
        {"site": "fx.app", "platform": "vercel", "title": "AI dance effects", "latest28_clicks": 5},
        {"site": "gx.app", "platform": "vercel", "title": "AI photo editor", "latest28_clicks": 9}]}, 1)
    m, stats = disc.Matcher(conn), {}
    launches = disc.launch_candidates(conn, m, SINCE, stats)
    hosted = disc.hosted_candidates(conn, m, SINCE, stats)
    assert len(launches) == 3 and [h["domain"] for h in hosted] == ["gx.app", "fx.app"]
    assert stats["launches"] == {"total": 6, "included": 3, "truncated": 3}
    assert stats["hosted"] == {"total": 2, "included": 2, "truncated": 0}
    assert [c["domain"] for c in launches] == ["l5.ai", "l4.ai", "l3.ai"]  # newest first, deterministic


def test_unmatched_exploration_is_bounded_fresh_and_labelled(conn, monkeypatch):
    monkeypatch.setattr(disc, "EXPLORE_LIMIT", 3)
    snap(conn, "ai baby dance", "new", 1.0, 50)                  # vocabulary match
    snap(conn, "skibidi wobble", "new", 0.5, 300)                # unmatched, fresh, fastest
    snap(conn, "grape fork", "spike", 2.0, 10)
    snap(conn, "zebra hop", "new", 0.5, 300)                     # ties with skibidi: keyword breaks the tie
    snap(conn, "plain old word", "old", 9.0, 999)                # unmatched but old: never explored
    snap(conn, "quiet watch", "watch", 0.1, 1)                   # fourth fresh one: over the limit
    stats = {}
    out = disc.search_candidates(conn, disc.Matcher(conn), SINCE, stats)
    voc = [c for c in out if c["discovery"] == disc.VOCABULARY]
    exp = [c for c in out if c["discovery"] == disc.EXPLORATION]
    assert [c["keyword"] for c in voc] == ["ai baby dance"] and voc[0]["matched_terms"]
    assert [c["keyword"] for c in exp] == ["skibidi wobble", "zebra hop", "grape fork"]
    assert all(c["channel"] == "search" and c["matched_terms"] == [] for c in exp)
    assert stats["search_exploration"] == {"total": 4, "included": 3, "truncated": 1}
    assert disc.search_candidates(conn, disc.Matcher(conn), SINCE, {}) == out  # stable


def test_exploration_stays_identifiable_after_merging(conn, paths, fake):
    snap(conn, "skibidi wobble", "new", 0.5, 300)
    normalize.launch_batch(conn, "lb", {"items": [{"source": "hn", "source_url": "x", "title": "Wobble AI video maker",
                                                   "url": "https://wobble.ai", "domain": "wobble.ai",
                                                   "keyword": "skibidi wobble"}]}, 1)
    snap(conn, "lonely sound", "new", 0.1, 5)
    out = paths.work(DAY1) / "candidates.json"
    stats = disc.discover(conn, DAY1, out)
    doc = json.loads(out.read_text(encoding="utf-8"))
    g = {x["label"]: x for x in doc["groups"]}
    merged = g["skibidi wobble"]
    assert merged["discovery"] == [disc.EXPLORATION, disc.VOCABULARY] and merged["exploration"]
    assert set(merged["channels"]) == {"search", "product"}
    assert g["lonely sound"]["discovery"] == [disc.EXPLORATION]
    assert doc["groups"][-1]["label"] == "lonely sound"  # exploration-only groups sort last
    assert doc["stats"]["search_exploration"]["included"] == 2 and stats["exploration_groups"] == 2
    assert not fake.calls  # exploration reads SQLite only: no Ge Fei calls


# ---- 2/3. evidence refs and fingerprints ----
def test_refs_are_global_and_conflicts_are_rejected(conn, paths):
    ingest(conn, paths, research_doc())
    base = research_doc()["evidence"][0]
    assert ingest(conn, paths, only(DAY1, evidence=[base]))["evidence"] == 0      # identical, same day
    assert ingest(conn, paths, only(D2, evidence=[base]), D2)["evidence"] == 0    # identical, later day
    with pytest.raises(InputError, match="ref e1 already names different evidence"):
        ingest(conn, paths, only(DAY1, evidence=[dict(base, value=101)]))         # same day, new content
    with pytest.raises(InputError, match="ref e1 already names different evidence"):
        ingest(conn, paths, only(D2, evidence=[dict(base, value=101)]), D2)       # cross day
    with pytest.raises(InputError, match="ref e1"):
        ingest(conn, paths, only(D2, evidence=[dict(base, note="new note")]), D2)
    assert db.one(conn, "SELECT COUNT(*) n FROM evidence WHERE ref='e1'")["n"] == 1
    with pytest.raises(sqlite3.IntegrityError):  # the database enforces it too
        conn.execute("INSERT INTO evidence (day, ref, entity, channel, source, collected_at, confidence, tag,"
                     " fingerprint) VALUES ('x','e1','trend:ai-baby-dance','social','s','t','low','估算','other')")


@pytest.mark.parametrize("field,value", [
    ("channel", "search"), ("source", "Instagram"), ("url", "https://other"), ("metric", "views"),
    ("value", 101), ("unit", "videos"), ("region", "GB"), ("sample_size", 7),
    ("metric_definition", "posts in 12h"), ("collected_at", "2026-11-13T10:00:00+08:00"), ("confidence", "high"),
    ("tag", "估算"), ("note", "different note"), ("entity", "opportunity:baby-dance-template"),
])
def test_each_meaningful_field_change_is_kept(conn, paths, field, value):
    ingest(conn, paths, research_doc())
    base = dict(research_doc()["evidence"][0], ref="")
    ingest(conn, paths, only(DAY1, evidence=[base]))
    before = db.one(conn, "SELECT COUNT(*) n FROM evidence")["n"]
    assert ingest(conn, paths, only(DAY1, evidence=[dict(base, **{field: value})]))["evidence"] == 1
    assert ingest(conn, paths, only(DAY1, evidence=[dict(base, **{field: value})]))["evidence"] == 0
    assert db.one(conn, "SELECT COUNT(*) n FROM evidence")["n"] == before + 1  # old row kept: append-only


def test_api_call_id_is_part_of_the_fingerprint(conn, paths, fake):
    from radar.gefei.client import Client
    c = Client(conn, "t", "https://seo.web.cafe", fake, DAY1)
    c.refresh_catalog()
    call = c.call("keyword_volume", {"keywords": ["ai baby dance"]})
    ingest(conn, paths, research_doc())
    base = dict(research_doc()["evidence"][1], ref="", value=12100)
    ingest(conn, paths, only(DAY1, evidence=[base]))
    assert ingest(conn, paths, only(DAY1, evidence=[dict(base, api_call_id=call.call_id)]))["evidence"] == 1


def test_same_instant_in_another_offset_is_the_same_evidence(conn, paths):
    ingest(conn, paths, research_doc())
    base = dict(research_doc()["evidence"][0], ref="")
    ingest(conn, paths, only(DAY1, evidence=[base]))
    utc = dict(base, collected_at="2026-11-13T01:00:00+00:00")  # == 09:00+08:00
    assert ingest(conn, paths, only(DAY1, evidence=[utc]))["evidence"] == 0


# ---- 4. historical reports ----
def test_rebuilding_an_old_report_ignores_later_information(conn, paths):
    doc = research_doc()
    opp = assessment("opportunity:baby-dance-template", decision="build", priority="P0", deep=DEEP,
                     next_steps=["go"], tracked={"kind": "evidence", "metric": "search_volume", "region": "US"})
    ingest(conn, paths, doc)
    decisions.ingest_assessments(conn, write(paths.work(DAY1) / "assessments.json",
                                             {"day": DAY1.isoformat(),
                                              "assessments": [assessment("trend:ai-baby-dance"), opp]}), DAY1)
    backtest.evaluate(conn, DAY1)
    daily.build(conn, DAY1, paths)
    deep.build(conn, DAY1, paths)
    day1_daily = paths.daily_report(DAY1).read_text(encoding="utf-8")
    day1_deep = paths.opportunity_report("baby-dance-template", DAY1).read_text(encoding="utf-8")

    # later days: back-dated evidence, a new link + site evidence, feedback, and settled backtests
    back = f"{DAY1.isoformat()}T08:00:00+08:00"
    ingest(conn, paths, only(D2, evidence=[
        dict(research_doc()["evidence"][0], ref="late-backdated", value=999, collected_at=back),
        {"ref": "late-site", "entity": "site:rival.ai", "channel": "market", "source": "S", "metric": "visits",
         "value": 5, "metric_definition": "visits", "collected_at": back, "confidence": "low", "tag": "估算"}],
        links=[{"from": "opportunity:baby-dance-template", "to": "site:rival.ai", "relation": "competitor"}]), D2)
    write(paths.feedback_inbox / "late.json", {"feedback": [
        {"entity": "opportunity:baby-dance-template", "field": "priority", "value": "P3", "reason": "late change",
         "author": "pm", "at": back}]})  # dated D1 but only known on D2
    decisions.ingest_feedback(conn, paths.feedback_inbox, D2)
    d15 = DAY1 + timedelta(days=14)
    ingest(conn, paths, only(D8, evidence=[dict(research_doc()["evidence"][0], ref="d8", value=300,
                                                collected_at=f"{D8.isoformat()}T09:00:00+08:00"),
                                           dict(research_doc()["evidence"][1], ref="d8s", value=2000,
                                                collected_at=f"{D8.isoformat()}T09:00:00+08:00")]), D8)
    ingest(conn, paths, only(d15, evidence=[dict(research_doc()["evidence"][1], ref="d15s", value=2500,
                                                 collected_at=f"{d15.isoformat()}T09:00:00+08:00")]), d15)
    backtest.evaluate(conn, d15)
    assert backtest.summary(conn)["lifecycle"]["scored"] == 2  # settled now ...
    assert backtest.summary(conn, as_of=DAY1)["lifecycle"]["scored"] == 0  # ... but not as of day 1
    assert ("opportunity:baby-dance-template", "site:rival.ai", "competitor") in current_links(conn)
    assert ("opportunity:baby-dance-template", "site:rival.ai", "competitor") not in current_links(conn, as_of=DAY1)

    daily.build(conn, DAY1, paths)
    deep.build(conn, DAY1, paths)
    assert paths.daily_report(DAY1).read_text(encoding="utf-8") == day1_daily
    rebuilt_deep = paths.opportunity_report("baby-dance-template", DAY1).read_text(encoding="utf-8")
    assert rebuilt_deep == day1_deep
    for leaked in ("late-backdated", "999", "rival.ai", "late change", "P3", "命中"):
        assert leaked not in rebuilt_deep and leaked not in day1_daily

    # the same opportunity viewed on day 15 does see the settled backtests and feedback
    st = decisions.effective(conn, "opportunity:baby-dance-template", d15)
    later = deep.render(conn, st, d15)
    assert "late change" in later and "得到支持" in later
    assert "rival.ai" not in later  # evidence/links stay frozen at the assessment day


# ---- 5. social coverage ----
def test_social_coverage_is_required_and_reported(conn, paths):
    doc = research_doc(social_coverage=[c for c in coverage() if c["platform"] != "Reddit"])
    with pytest.raises(InputError, match="missing \\['Reddit'\\]"):
        ingest(conn, paths, doc)
    bad = coverage(Instagram=("failed", ""))
    with pytest.raises(InputError, match="needs a reason"):
        ingest(conn, paths, research_doc(social_coverage=bad))
    with pytest.raises(InputError, match="must be one of"):
        ingest(conn, paths, research_doc(social_coverage=coverage() + [{"platform": "Douyin", "status": "covered",
                                                                        "window": "x"}]))
    ingest(conn, paths, research_doc(social_coverage=coverage(Instagram=("failed", "login wall"),
                                                              X=("not_attempted", "out of time")),
                                     notes="CapCut template pages were slow"))
    decisions.ingest_assessments(conn, write(paths.work(DAY1) / "assessments.json",
                                             {"day": DAY1.isoformat(), "assessments": []}), DAY1)
    daily.build(conn, DAY1, paths)
    text = paths.daily_report(DAY1).read_text(encoding="utf-8")
    assert "> 社交调研覆盖：6/8 个来源完成；未完成：Instagram（失败）、X（未进行）。" in text
    assert "| Instagram | 失败 | — | 未知 | login wall |" in text
    assert "调研备注：CapCut template pages were slow" in text
    assert "- 社交调研：X：not_attempted：out of time" in text  # also a gap


def test_report_without_research_says_coverage_is_unknown(conn, paths):
    daily.build(conn, DAY1, paths)
    assert "社交调研覆盖：未记录" in paths.daily_report(DAY1).read_text(encoding="utf-8")
