"""Regression tests: research day vs observed-at vs ingested-at, across every historical query."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from radar import backtest, db, decisions
from radar.config import end_of
from radar.reports import daily, deep
from radar.reports.common import evidence_rows
from radar.research.ingest import InputError, current_links, ingest_research
from conftest import DAY1, DEEP, assessment, coverage, research_doc, write

D = {n: DAY1 + timedelta(days=n) for n in range(0, 20)}


def ingest(conn, paths, doc, day, clock):
    clock.advance_to(day)
    n = len(list(paths.work(day).glob("*"))) if paths.work(day).is_dir() else 0
    return ingest_research(conn, write(paths.work(day) / f"r{n}.json", doc), day)


def assess(conn, paths, items, day, clock):
    clock.advance_to(day)
    return decisions.ingest_assessments(conn, write(paths.work(day) / "assessments.json",
                                                    {"day": day.isoformat(), "assessments": items}), day)


def only(day, **over):
    return research_doc(day=day, **({"trends": [], "formats": [], "opportunities": [], "links": [], "evidence": [],
                                     "gaps": []} | over))


def obs(observed, value, ref, which=0):
    """Evidence measured like research_doc() row `which`, observed on day `observed`."""
    return dict(research_doc()["evidence"][which], ref=ref, value=value,
                collected_at=f"{observed.isoformat()}T09:00:00+08:00")


def setup(conn, paths, clock):
    ingest(conn, paths, research_doc(), D[0], clock)
    opp = assessment("opportunity:baby-dance-template", decision="build", priority="P0", deep=DEEP, next_steps=["go"],
                     tracked={"kind": "evidence", "metric": "search_volume", "region": "US"})
    assess(conn, paths, [assessment("trend:ai-baby-dance"), opp], D[0], clock)


def insert_revision(conn, entity, day, created_at, **changes):
    """A revision filed under `day` but created later (what older code or a manual edit could produce)."""
    last = db.one(conn, "SELECT * FROM assessments WHERE entity=? AND day=? ORDER BY revision DESC LIMIT 1",
                  (entity, day.isoformat()))
    row = {k: v for k, v in last.items() if k != "id"} | changes
    row |= {"revision": last["revision"] + 1, "created_at": created_at, "content_hash": "manual"}
    return db.insert(conn, "assessments", row)


# ---- 1/2: outcome observed on D8, ingested on D10 ----
def test_outcome_settles_when_ingested_not_when_observed(conn, paths, clock):
    setup(conn, paths, clock)
    ingest(conn, paths, only(D[10], evidence=[obs(D[7], 130, "late-obs")]), D[10], clock)
    backtest.evaluate(conn, D[10])
    trend = lambda rows: next(r for r in rows if r["entity"] == "trend:ai-baby-dance")  # noqa: E731
    for day in (D[7], D[8], D[9]):
        r = trend(backtest.official(conn, system="lifecycle", as_of=day))
        assert r["outcome"] == "pending" and r["outcome_at"] is None, day
    r = trend(backtest.official(conn, system="lifecycle", as_of=D[10]))
    assert r["outcome"] == "hit" and r["outcome_at"][:10] == D[7].isoformat()  # observation date kept
    assert r["outcome_ingested_at"][:10] == D[10].isoformat()
    assert [x["entity"] for x in backtest.resolved_on(conn, D[10])] == ["trend:ai-baby-dance"]
    assert backtest.resolved_on(conn, D[7]) == [] and backtest.resolved_on(conn, D[9]) == []
    stored = trend(backtest.official(conn, system="lifecycle"))
    assert stored["outcome"] == "hit"  # the stored (current) result agrees with as-of D10


def test_historical_daily_report_does_not_see_a_later_outcome(conn, paths, clock):
    setup(conn, paths, clock)
    clock.advance_to(D[9])
    daily.build(conn, D[9], paths)
    before = paths.daily_report(D[9]).read_text(encoding="utf-8")
    ingest(conn, paths, only(D[10], evidence=[obs(D[7], 130, "late-obs")]), D[10], clock)
    backtest.evaluate(conn, D[10])
    daily.build(conn, D[9], paths)
    assert paths.daily_report(D[9]).read_text(encoding="utf-8") == before
    assert "命中" not in before
    daily.build(conn, D[10], paths)
    assert "今日结算" in paths.daily_report(D[10]).read_text(encoding="utf-8")


# ---- 3/4: link events ----
def link_event(conn, src, dst, rel, action, day, at):
    db.insert(conn, "link_events", {"src": src, "dst": dst, "relation": rel, "action": action, "origin": "test",
                                    "note": "", "day": day.isoformat(), "at": at})


def test_backdated_link_add_and_remove_respect_recording_time(conn, paths, clock):
    setup(conn, paths, clock)
    t, o = "trend:ai-baby-dance", "opportunity:baby-dance-template"
    link_event(conn, t, o, "drives", "add", D[0], end_of(D[3]))            # filed under D0, recorded D3
    assert (t, o, "drives") not in current_links(conn, as_of=D[0])
    assert (t, o, "drives") not in current_links(conn, as_of=D[2])
    assert (t, o, "drives") in current_links(conn, as_of=D[3])
    link_event(conn, t, "format:photo-to-dance", "uses", "remove", D[0], end_of(D[5]))  # backdated removal
    assert (t, "format:photo-to-dance", "uses") in current_links(conn, as_of=D[4])
    assert (t, "format:photo-to-dance", "uses") not in current_links(conn, as_of=D[5])
    assert (t, "format:photo-to-dance", "uses") not in current_links(conn)
    # a historical deep report keeps the links of its frozen assessment
    st = decisions.effective(conn, o, D[0])
    assert "drives" not in deep.render(conn, st, D[6]).split("## 证据清单")[0]


def test_link_replay_follows_insertion_order_not_research_day(conn, clock):
    t, f = "trend:x", "format:y"
    link_event(conn, t, f, "uses", "add", D[2], f"{D[2].isoformat()}T10:00:00+08:00")
    link_event(conn, t, f, "uses", "remove", D[0], f"{D[2].isoformat()}T11:00:00+08:00")  # labelled earlier day
    assert (t, f, "uses") not in current_links(conn)                    # remove happened after the add
    assert (t, f, "uses") not in current_links(conn, as_of=D[2])
    link_event(conn, t, f, "uses", "add", D[1], f"{D[2].isoformat()}T12:00:00+08:00")
    assert (t, f, "uses") in current_links(conn) and (t, f, "uses") in current_links(conn, as_of=D[2])
    assert current_links(conn) == current_links(conn)  # deterministic


def test_add_link_event_stays_idempotent(conn, paths, clock):
    setup(conn, paths, clock)
    n = db.one(conn, "SELECT COUNT(*) n FROM link_events")["n"]
    assert ingest(conn, paths, research_doc(), D[0], clock)["links"] == 0
    assert db.one(conn, "SELECT COUNT(*) n FROM link_events")["n"] == n


# ---- 5/6/7: assessment revisions created after their research day ----
def test_revisions_are_chosen_among_those_existing_at_the_cutoff(conn, paths, clock):
    setup(conn, paths, clock)
    trend = "trend:ai-baby-dance"
    daily.build(conn, D[0], paths)
    before = paths.daily_report(D[0]).read_text(encoding="utf-8")
    insert_revision(conn, trend, D[0], end_of(D[2]), lifecycle="fading", decision="skip")
    assert decisions.effective(conn, trend, D[0])["revision"] == 1
    assert decisions.effective(conn, trend, D[1])["revision"] == 1
    assert decisions.effective(conn, trend, D[2])["revision"] == 2
    assert decisions.effective(conn, trend)["revision"] == 2
    daily.build(conn, D[0], paths)
    assert paths.daily_report(D[0]).read_text(encoding="utf-8") == before


def test_official_backtests_use_the_same_revision_boundary(conn, paths, clock):
    setup(conn, paths, clock)
    trend = "trend:ai-baby-dance"
    ingest(conn, paths, only(D[7], evidence=[obs(D[7], 130, "d7")]), D[7], clock)
    clock.advance_to(D[8])
    insert_revision(conn, trend, D[0], end_of(D[9]), lifecycle="fading",
                    body_json=json.dumps(json.loads(db.one(conn, "SELECT body_json FROM assessments WHERE entity=?"
                                                                 " AND revision=1", (trend,))["body_json"])
                                         | {"expected_direction": "falling"}))
    backtest.evaluate(conn, D[10])
    at8 = [r for r in backtest.official(conn, system="lifecycle", as_of=D[8]) if r["entity"] == trend]
    at9 = [r for r in backtest.official(conn, system="lifecycle", as_of=D[9]) if r["entity"] == trend]
    assert [(r["revision"], r["outcome"]) for r in at8] == [(1, "hit")]    # emerging, rose 30%
    assert [(r["revision"], r["outcome"]) for r in at9] == [(2, "miss")]   # fading, but it rose
    assert backtest.summary(conn, as_of=D[8])["lifecycle"]["good"] == 1
    assert backtest.summary(conn, as_of=D[9])["lifecycle"]["good"] == 0


def test_writing_research_for_another_day_is_refused(conn, paths, clock):
    setup(conn, paths, clock)
    clock.advance_to(D[3])
    path = write(paths.work(D[0]) / "again.json", research_doc())
    assert ingest_research(conn, path, D[0])["evidence"] == 0               # identical: allowed, no-op
    changed = write(paths.work(D[0]) / "late.json", only(D[0], evidence=[obs(D[0], 5, "backdated")]))
    with pytest.raises(InputError, match="Backdated or future research is not accepted"):
        ingest_research(conn, changed, D[0])
    assert not db.one(conn, "SELECT 1 FROM evidence WHERE ref='backdated'")  # rolled back entirely
    future = write(paths.work(D[5]) / "f.json", only(D[5], evidence=[obs(D[3], 5, "future")]))
    with pytest.raises(InputError, match="not accepted"):
        ingest_research(conn, future, D[5])
    same = write(paths.work(D[0]) / "assessments.json", {"day": D[0].isoformat(), "assessments": [
        assessment("trend:ai-baby-dance")]})
    assert decisions.ingest_assessments(conn, same, D[0]) == {"new": 0, "unchanged": 1}
    edited = write(paths.work(D[0]) / "assessments.json", {"day": D[0].isoformat(), "assessments": [
        assessment("trend:ai-baby-dance", summary="edited later")]})
    with pytest.raises(InputError, match="not accepted"):
        decisions.ingest_assessments(conn, edited, D[0])
    assert db.one(conn, "SELECT COUNT(*) n FROM assessments WHERE entity='trend:ai-baby-dance'")["n"] == 1


# ---- 8: feedback ----
def test_backdated_feedback_is_invisible_before_it_was_ingested(conn, paths, clock):
    setup(conn, paths, clock)
    opp = "opportunity:baby-dance-template"
    deep.build(conn, D[0], paths)
    before = paths.opportunity_report("baby-dance-template", D[0]).read_text(encoding="utf-8")
    clock.advance_to(D[3])
    write(paths.feedback_inbox / "late.json", {"feedback": [
        {"entity": opp, "field": "priority", "value": "P3", "reason": "backdated note", "author": "pm",
         "at": f"{D[0].isoformat()}T09:00:00+08:00"}]})
    decisions.ingest_feedback(conn, paths.feedback_inbox, D[3])
    for day in (D[0], D[2]):
        assert decisions.effective(conn, opp, day)["priority"] == "P0"
        assert "backdated note" not in deep.render(conn, decisions.effective(conn, opp, day), day)
    assert decisions.effective(conn, opp, D[3])["priority"] == "P3"
    assert "backdated note" in deep.render(conn, decisions.effective(conn, opp, D[3]), D[3])
    deep.build(conn, D[0], paths)
    assert paths.opportunity_report("baby-dance-template", D[0]).read_text(encoding="utf-8") == before


# ---- 9: evidence, gaps, research metadata ----
def test_evidence_and_gaps_count_from_ingestion(conn, paths, clock):
    setup(conn, paths, clock)
    ingest(conn, paths, only(D[3], evidence=[obs(D[0], 777, "late-collected-early")]), D[3], clock)
    entities = ["trend:ai-baby-dance"]
    assert "late-collected-early" not in "\n".join(evidence_rows(conn, entities, end_of(D[0])))
    assert "late-collected-early" not in "\n".join(evidence_rows(conn, entities, end_of(D[2])))
    assert "late-collected-early" in "\n".join(evidence_rows(conn, entities, end_of(D[3])))
    st = decisions.effective(conn, "trend:ai-baby-dance", D[0])
    assert decisions.tracked_point(conn, st, D[0]).value == 100   # not the later-ingested 777
    assert decisions.tracked_point(conn, st, D[3]).value == 777   # observed D0 09:00, latest by time

    daily.build(conn, D[0], paths)
    before = paths.daily_report(D[0]).read_text(encoding="utf-8")
    from radar.research.ingest import record_gap
    record_gap(conn, D[0], "飞书发布", "failed on a later rerun")  # code gap filed under D0, recorded D3
    daily.build(conn, D[0], paths)
    assert paths.daily_report(D[0]).read_text(encoding="utf-8") == before
    assert db.one(conn, "SELECT ingested_at FROM gaps WHERE note='failed on a later rerun'")["ingested_at"][:10] \
        == D[3].isoformat()


def test_ingestion_timestamps_are_wall_clock_not_inputs(conn, paths, clock):
    setup(conn, paths, clock)
    row = db.one(conn, "SELECT day, collected_at, ingested_at FROM evidence WHERE ref='e1'")
    assert row["day"] == D[0].isoformat() and row["collected_at"].startswith(f"{D[0].isoformat()}T09:00")
    assert row["ingested_at"].startswith(f"{D[0].isoformat()}T18:")  # the (fake) wall clock
    clock.advance_to(D[2])
    write(paths.feedback_inbox / "f.json", {"feedback": [
        {"entity": "trend:ai-baby-dance", "field": "direction", "value": "look at CapCut", "reason": "r",
         "author": "pm", "at": "2020-01-01T00:00:00Z"}]})
    decisions.ingest_feedback(conn, paths.feedback_inbox, D[2])
    f = db.one(conn, "SELECT at, ingested_at FROM feedback")
    assert f["at"].startswith("2020-01-01T08:00") and f["ingested_at"][:10] == D[2].isoformat()


# ---- 10: social coverage ----
def test_covered_source_must_say_whether_signals_were_found(conn, paths, clock):
    cov = coverage()
    cov[0] = dict(cov[0], signals="unknown")
    with pytest.raises(InputError, match="covered must report signals found or none"):
        ingest(conn, paths, research_doc(social_coverage=cov), D[0], clock)
    cov[0] = dict(cov[0], signals="none")
    ingest(conn, paths, research_doc(social_coverage=cov), D[0], clock)
    partial = coverage(TikTok=("partial", "rate limited"))
    assert next(c for c in partial if c["platform"] == "TikTok")["signals"] == "unknown"  # allowed when incomplete
    ingest(conn, paths, research_doc(social_coverage=partial), D[0], clock)


def test_fresh_database_is_schema_3_and_old_versions_are_refused(tmp_path):
    import sqlite3
    c = db.connect(tmp_path / "radar.db")
    assert db.SCHEMA_VERSION == 3 and c.execute("PRAGMA user_version").fetchone()[0] == 3
    cols = {t: {r[1] for r in c.execute(f"PRAGMA table_info({t})")} for t in
            ("evidence", "feedback", "gaps", "backtest_results")}
    assert "ingested_at" in cols["evidence"] and "ingested_at" in cols["feedback"] and "ingested_at" in cols["gaps"]
    assert "outcome_ingested_at" in cols["backtest_results"] and "ingested_day" not in cols["feedback"]
    c.close()
    old = tmp_path / "old.db"
    raw = sqlite3.connect(old)
    raw.execute("CREATE TABLE evidence (id INTEGER)")
    raw.execute("PRAGMA user_version=2")
    raw.close()
    with pytest.raises(db.SchemaError, match="schema version 2; this code needs 3. There are no migrations"):
        db.connect(old)
