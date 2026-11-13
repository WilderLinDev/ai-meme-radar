from __future__ import annotations

from datetime import timedelta

from radar import db, lark, pipeline
from conftest import DAY1, DEEP, FakeLark, assessment, make_ctx, research_doc, write

D2 = DAY1 + timedelta(days=1)


def ctx(paths, conn, settings, fake, larkfake, day=DAY1):
    return make_ctx(paths, conn, settings, fake, larkfake, day)


def day1_files(paths):
    write(paths.work(DAY1) / "research.json", research_doc())
    opp = assessment("opportunity:baby-dance-template", decision="build", priority="P0", deep=DEEP,
                     next_steps=["ship it"], tracked={"kind": "evidence", "metric": "search_volume", "region": "US"})
    write(paths.work(DAY1) / "assessments.json", {"day": DAY1.isoformat(), "assessments": [
        assessment("trend:ai-baby-dance", lifecycle="early_signal", decision="validate", priority="P1",
                   next_steps=["check CapCut"]), opp]})


def test_full_run_waits_then_delivers_and_resumes(paths, conn, settings, fake):
    lk = FakeLark()
    c = ctx(paths, conn, settings, fake, lk)
    assert pipeline.run(c) == pipeline.WAITING  # no research.json yet
    assert (paths.work(DAY1) / "candidates.json").is_file()
    write(paths.work(DAY1) / "research.json", research_doc())
    assert pipeline.run(c) == pipeline.WAITING  # no assessments.json yet
    assert (paths.work(DAY1) / "assessments.draft.json").is_file()
    day1_files(paths)
    assert pipeline.run(c) == pipeline.DONE

    daily = paths.daily_report(DAY1).read_text(encoding="utf-8")
    for h in ("## 1. 今日最值得关注的机会", "## 2. 新发现的早期信号", "## 3. 重要趋势变化", "## 4. 决策变化",
              "## 5. 需要进一步验证的机会", "## 6. 其他值得关注的趋势", "## 回测", "## 数据缺口"):
        assert h in daily
    assert "Baby Dance AI Template" in daily and "早期信号 · 验证 · P1" in daily
    assert "Instagram：login wall" in daily
    deep = paths.opportunity_report("baby-dance-template", DAY1).read_text(encoding="utf-8")
    assert "## 为什么是现在" in deep and "## 证据清单" in deep and "【第三方读数】" in deep
    assert "AI Baby Dance" in deep  # trend reached through the format link

    docs = {d["doc_key"]: d for d in lark.documents(conn)}
    assert set(docs) == {"daily/2026-11-13", "opportunity/baby-dance-template"}
    assert all(d["status"] == "synced" and d["url"] for d in docs.values())
    first = lk.publishes[0]
    assert first[first.index("--parent-token") + 1] in ("wikiDaily", "wikiOpp")

    # rerun: the gate is rechecked, but Ge Fei batches are not re-synced and nothing is republished
    n_calls, n_lark = len(fake.calls), len(lk.publishes)
    assert pipeline.run(c) == pipeline.DONE
    assert len(lk.publishes) == n_lark
    assert not [p for m, p, q, b in fake.calls[n_calls:] if "/batches/" in p and p.count("/") > 4]
    assert paths.daily_report(DAY1).read_text(encoding="utf-8") == daily  # preflight calls do not change it

    # raw Ge Fei data stays local: nothing but report markdown went to Lark
    for args in lk.publishes:
        assert args[args.index("--content") + 1].endswith(".md")


def test_day_two_reports_changes_only_and_lark_updates_in_place(paths, conn, settings, fake):
    lk = FakeLark()
    day1_files(paths)
    assert pipeline.run(ctx(paths, conn, settings, fake, lk)) == pipeline.DONE

    write(paths.work(D2) / "research.json", research_doc(day=D2, trends=[], formats=[], opportunities=[], links=[],
                                                         evidence=[], gaps=[]))
    trend = assessment("trend:ai-baby-dance", lifecycle="emerging", decision="validate", priority="P1",
                       next_steps=["check CapCut"])
    write(paths.work(D2) / "assessments.json", {"day": D2.isoformat(), "assessments": [trend]})
    write(paths.feedback_inbox / "pm.json", {"feedback": [
        {"entity": "opportunity:baby-dance-template", "field": "priority", "value": "P1", "reason": "capacity",
         "author": "pm", "at": f"{D2.isoformat()}T08:00:00+08:00"}]})
    lk.fail = True
    assert pipeline.run(ctx(paths, conn, settings, fake, lk, D2)) == pipeline.FAILED  # delivery is required
    daily = paths.daily_report(D2).read_text(encoding="utf-8")
    assert "生命周期 早期信号 → 上升期" in daily
    assert "立即做/P0 → 立即做/P1（人工）" in daily
    assert "人工修改：优先级 P0 → P1（pm：capacity）" in daily
    assert paths.daily_report(D2).is_file()
    assert db.one(conn, "SELECT status FROM lark_docs WHERE doc_key='daily/2026-11-14'")["status"] == "failed"
    assert db.one(conn, "SELECT event FROM run_events WHERE stage='publish' ORDER BY id DESC")["event"] == "failed"

    lk.fail = False
    assert pipeline.run(ctx(paths, conn, settings, fake, lk, D2)) == pipeline.DONE
    created = [a for a in lk.publishes if "+create" in a]
    assert db.one(conn, "SELECT status FROM lark_docs WHERE doc_key='daily/2026-11-14'")["status"] == "synced"
    # the opportunity doc is never duplicated: day 2 did not re-assess it, and its doc id is unchanged
    titles = [a[a.index("--title") + 1] for a in created]
    assert titles.count("深度研究：Baby Dance AI Template") == 1


def test_unchanged_entities_are_one_liners(paths, conn, settings, fake):
    lk = FakeLark()
    day1_files(paths)
    pipeline.run(ctx(paths, conn, settings, fake, lk))
    write(paths.work(D2) / "research.json", research_doc(day=D2, trends=[], formats=[], opportunities=[], links=[],
                                                         evidence=[], gaps=[]))
    write(paths.work(D2) / "assessments.json", {"day": D2.isoformat(), "assessments": []})
    pipeline.run(ctx(paths, conn, settings, fake, lk, D2))
    daily = paths.daily_report(D2).read_text(encoding="utf-8")
    assert "较上次日报无变化，详见深度报告" in daily
    assert "### Baby Dance AI Template" not in daily  # not re-expanded
    assert "没有决策或优先级变化" in daily
