from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from radar import backtest, db, decisions
from radar.gefei.client import Client
from radar.research.discover import discover
from radar.research.ingest import InputError, current_links, ingest_research
from conftest import DAY1, DEEP, advance, assessment, research_doc, write


def ingest(conn, paths, doc, day=DAY1):
    advance(day)
    return ingest_research(conn, write(paths.work(day) / "research.json", doc), day)


def assess(conn, paths, items, day=DAY1):
    advance(day)
    return decisions.ingest_assessments(conn, write(paths.work(day) / "assessments.json",
                                                    {"day": day.isoformat(), "assessments": items}), day)


def test_research_ingest_is_idempotent(conn, paths):
    s1 = ingest(conn, paths, research_doc())
    s2 = ingest(conn, paths, research_doc())
    assert s1 == {"entities": 3, "links": 3, "evidence": 2, "gaps": 1, "metadata": 1}
    assert s2 == {"entities": 0, "links": 0, "evidence": 0, "gaps": 0, "metadata": 0}
    assert ("trend:ai-baby-dance", "keyword:ai baby dance", "searched_as") in current_links(conn)


def test_duplicates_and_undefined_refs_are_rejected(conn, paths):
    ingest(conn, paths, research_doc())
    dup = research_doc(trends=[{"id": "baby-dancing", "name": "Baby Dance AI", "aliases": ["AI baby dance"]}],
                       formats=[], opportunities=[], links=[], evidence=[], gaps=[])
    with pytest.raises(InputError) as e:
        ingest(conn, paths, dup)
    assert "duplicates existing trend:ai-baby-dance" in str(e.value)
    bad = research_doc(trends=[], formats=[], opportunities=[], evidence=[], gaps=[],
                       links=[{"from": "trend:nope", "to": "format:photo-to-dance", "relation": "uses"}])
    with pytest.raises(InputError, match="trend:nope is not defined"):
        ingest(conn, paths, bad)
    with pytest.raises(InputError, match="not allowed"):
        ingest(conn, paths, research_doc(links=[{"from": "keyword:x", "to": "trend:ai-baby-dance",
                                                 "relation": "uses"}]))


def test_cited_api_numbers_must_match_the_recorded_response(conn, paths, fake):
    c = Client(conn, "t", "https://seo.web.cafe", fake, DAY1)
    c.refresh_catalog()
    call = c.call("keyword_volume", {"keywords": ["ai baby dance"]})
    ev = dict(research_doc()["evidence"][1], api_call_id=call.call_id, value=99999)
    with pytest.raises(InputError, match="does not appear in call"):
        ingest(conn, paths, research_doc(evidence=[ev]))
    ingest(conn, paths, research_doc(evidence=[dict(ev, value=12100, ref="e9")]))
    ingest(conn, paths, research_doc(evidence=[dict(ev, value=99999, tag="估算", ref="e10")]))


def test_evidence_needs_definitions_and_timezones(conn, paths):
    ev = dict(research_doc()["evidence"][0], metric_definition="")
    with pytest.raises(InputError, match="metric_definition"):
        ingest(conn, paths, research_doc(evidence=[ev]))
    ev = dict(research_doc()["evidence"][0], collected_at="2026-11-13T09:00:00")
    with pytest.raises(InputError, match="timezone"):
        ingest(conn, paths, research_doc(evidence=[ev]))


def test_scaffold_ingest_revisions_and_key_opportunity_rules(conn, paths):
    ingest(conn, paths, research_doc())
    n = decisions.scaffold(conn, DAY1, paths.work(DAY1) / "assessments.draft.json")
    draft = json.loads((paths.work(DAY1) / "assessments.draft.json").read_text(encoding="utf-8"))
    assert n == 2 and {a["entity"] for a in draft["assessments"]} == {"trend:ai-baby-dance",
                                                                       "opportunity:baby-dance-template"}
    assert draft["assessments"][0]["facts"]["series"]

    opp = assessment("opportunity:baby-dance-template", decision="validate", priority="P0",
                     tracked={"kind": "evidence", "metric": "search_volume", "region": "US"},
                     next_steps=["ship a test template"])
    with pytest.raises(InputError, match="needs deep sections"):
        assess(conn, paths, [opp])
    opp["deep"] = DEEP
    assert assess(conn, paths, [assessment("trend:ai-baby-dance"), opp]) == {"new": 2, "unchanged": 0}
    assert assess(conn, paths, [assessment("trend:ai-baby-dance"), opp]) == {"new": 0, "unchanged": 2}
    opp2 = dict(opp, priority="P1")
    assess(conn, paths, [opp2])
    revs = db.rows(conn, "SELECT revision, priority FROM assessments WHERE entity=? ORDER BY revision",
                   ("opportunity:baby-dance-template",))
    assert revs == [{"revision": 1, "priority": "P0"}, {"revision": 2, "priority": "P1"}]  # history kept
    st = decisions.effective(conn, "opportunity:baby-dance-template")
    assert st["priority"] == "P1" and decisions.is_key(st)
    snap = json.loads(db.one(conn, "SELECT snapshot_json FROM assessments WHERE revision=1 AND entity=?",
                             ("opportunity:baby-dance-template",))["snapshot_json"])
    assert snap["baseline"]["value"] == 1000


def test_feedback_overrides_without_rewriting_history(conn, paths):
    ingest(conn, paths, research_doc())
    assess(conn, paths, [assessment("trend:ai-baby-dance")])
    write(paths.feedback_inbox / "a.json", {"feedback": [
        {"entity": "trend:ai-baby-dance", "field": "decision", "value": "validate", "reason": "client asked",
         "author": "pm", "at": "2099-01-01T10:00:00+08:00"},
        {"entity": "trend:ai-baby-dance", "field": "link_remove", "value": "searched_as->keyword:ai baby dance",
         "reason": "wrong keyword", "author": "pm", "at": "2099-01-01T10:00:00+08:00"}]})
    assert decisions.ingest_feedback(conn, paths.feedback_inbox, DAY1) == {"files": 1, "applied": 2}
    assert decisions.ingest_feedback(conn, paths.feedback_inbox, DAY1)["applied"] == 0
    st = decisions.effective(conn, "trend:ai-baby-dance")
    assert st["decision"] == "validate" and st["overrides"][0]["from"] == "monitor"
    assert db.one(conn, "SELECT decision FROM assessments")["decision"] == "monitor"
    assert db.one(conn, "SELECT old_value FROM feedback WHERE field='decision'")["old_value"] == "monitor"
    assert ("trend:ai-baby-dance", "keyword:ai baby dance", "searched_as") not in current_links(conn)
    assert db.one(conn, "SELECT COUNT(*) n FROM link_events")["n"] == 4  # 3 adds + 1 remove


def _evidence(day: date, value: float, ref: str, entity="trend:ai-baby-dance", metric="posts_24h", **over):
    """An observation measured exactly like the matching research_doc() evidence row."""
    base = next(e for e in research_doc()["evidence"] if e["entity"] == entity and e["metric"] == metric)
    return dict(base, ref=ref, value=value, collected_at=f"{day.isoformat()}T09:00:00+08:00", **over)


def test_backtests_use_frozen_baselines(conn, paths):
    ingest(conn, paths, research_doc())
    assess(conn, paths, [assessment("trend:ai-baby-dance", lifecycle="emerging"),
                         assessment("opportunity:baby-dance-template", decision="skip", priority="P3",
                                    tracked={"kind": "evidence", "metric": "search_volume", "region": "US"})])
    assert backtest.evaluate(conn, DAY1)["lifecycle"] == {"pending": 2}

    # a late, back-dated observation must not move the frozen baseline
    late = DAY1 - timedelta(days=1)
    ingest(conn, paths, research_doc(trends=[], formats=[], opportunities=[], links=[], gaps=[],
                                     evidence=[_evidence(late, 10, "back")]), DAY1)
    d8 = DAY1 + timedelta(days=7)
    ingest(conn, paths, research_doc(day=d8, trends=[], formats=[], opportunities=[], links=[], gaps=[],
                                     evidence=[_evidence(d8, 130, "d8"),
                                               _evidence(d8, 1500, "d8s", "opportunity:baby-dance-template",
                                                         "search_volume")]), d8)
    d15 = DAY1 + timedelta(days=14)
    ingest(conn, paths, research_doc(day=d15, trends=[], formats=[], opportunities=[], links=[], gaps=[],
                                     evidence=[_evidence(d15, 1400, "d15s", "opportunity:baby-dance-template",
                                                         "search_volume")]), d15)
    backtest.evaluate(conn, d15)
    rows = {(r["system"], r["entity"]): r for r in db.rows(
        conn, "SELECT b.*, a.entity FROM backtest_results b JOIN assessments a ON a.id=b.assessment_id")}
    lc = rows[("lifecycle", "trend:ai-baby-dance")]
    assert lc["baseline_value"] == 100 and lc["outcome_value"] == 130 and lc["outcome"] == "hit"
    dec = rows[("decision", "opportunity:baby-dance-template")]
    assert dec["baseline_value"] == 1000 and dec["outcome_value"] == 1400 and dec["outcome"] == "missed"
    s = backtest.summary(conn)
    assert s["lifecycle"]["good"] == 2 and s["decision"]["rate"] == 0.0


def test_discover_merges_channels_and_suggests_links(conn, paths, fake, settings):
    from radar.gefei.sync import Syncer
    ingest(conn, paths, research_doc(links=research_doc()["links"][:2]))
    Syncer(conn, Client(conn, "t", "https://seo.web.cafe", fake, DAY1), settings).run()
    out = paths.work(DAY1) / "candidates.json"
    stats = discover(conn, DAY1, out)
    doc = json.loads(out.read_text(encoding="utf-8"))
    labels = {g["label"]: g for g in doc["groups"]}
    g = labels["AI Baby Dance"]
    assert set(g["channels"]) == {"search", "product"}  # keyword + launch sharing the keyword
    assert "trend:ai-baby-dance" in g["matches"]
    assert not any("mortgage" in g["label"] or "Tax" in g["label"] for g in doc["groups"])
    assert {"from": "trend:ai-baby-dance", "to": "keyword:ai baby dance", "relation": "searched_as",
            "because": "AI Baby Dance"} in doc["link_suggestions"]
    assert stats["market"] >= 1
