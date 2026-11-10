"""Golden test: the migrated 2026-11-10 judgments build into a pack and both reports."""
from __future__ import annotations

import json
from zoneinfo import ZoneInfo

import pytest
from docx import Document as read_docx

from radar import pipeline
from radar.config import Settings
from radar.csvio import DataError
from radar.export.lark import build_records

from .conftest import DAY, FIXTURE

OLD_TOTALS = {  # from the 2026-11-10 pack before the refactor
    "cat-ultra-bee": 76, "shaking-head": 71, "lastchristmas": 67, "shoulder-carry": 66, "can-i-ride": 65,
    "bicep-heart": 58, "then-i-walk-in": 57, "halloweentransition": 27,
}


def test_build_fixture(workspace):
    result = pipeline.build(workspace, Settings(), DAY)
    pack = result.pack
    totals = {m.id: m.facts.total for m in pack.memes}
    for meme_id, total in OLD_TOTALS.items():
        assert totals[meme_id] == total
    assert len(pack.memes) == 26
    assert all(m.facts.total == m.judgment.scores.total for m in pack.memes)

    cat = next(m for m in pack.memes if m.id == "cat-ultra-bee")
    assert cat.facts.days_hot == 5
    assert cat.facts.tiktok_share.enough and cat.facts.tiktok_share.n == 6
    assert cat.facts.watchlist_handles == ["TikTok@memescreens"]

    head = next(m for m in pack.memes if m.id == "shaking-head")
    assert head.facts.peak_status == "rising"  # the 11/10 partial point is ignored
    assert head.facts.primary_value == 486

    xmas = next(m for m in pack.memes if m.id == "lastchristmas")
    assert xmas.facts.source_label == "TikTok Top100·DE,GB,US"
    assert xmas.facts.peak_status == "near_peak"

    md = (workspace.report_dir(DAY) / "daily-report.md").read_text(encoding="utf-8")
    for heading in ("一、总排名", "2.1 做", "2.2 观望", "2.3 不做", "三、早期信号", "回测"):
        assert heading in md
    # make gets full blocks; skip gets no section of its own
    assert md.count("##### 怎么做") == sum(1 for m in pack.memes if m.judgment.verdict == "make")
    assert '<a id="meme-halloweentransition">' not in md

    docx_text = "\n".join(p.text for p in read_docx(workspace.report_dir(DAY) / "daily-report.docx").paragraphs)
    assert "Cat on Ultra Bee" in docx_text and "怎么做" in docx_text

    evals = json.loads(workspace.backtest_json.read_text(encoding="utf-8"))["evaluations"]
    assert {e["result"] for e in evals} == {"pending"}


def test_build_is_idempotent(workspace):
    pipeline.build(workspace, Settings(), DAY, render=False)
    first = workspace.tracker.read_text(encoding="utf-8")
    pipeline.build(workspace, Settings(), DAY, render=False)
    assert workspace.tracker.read_text(encoding="utf-8") == first


def test_unaccounted_hashtag_blocks_build(workspace):
    top = workspace.raw_dir(DAY) / "cc-top100.csv"
    top.write_text(top.read_text(encoding="utf-8") + "US,7,99,#brandnewthing,1K,1M,\n", encoding="utf-8")
    with pytest.raises(DataError, match="brandnewthing"):
        pipeline.build(workspace, Settings(), DAY, render=False)


def test_override_needs_reason(workspace):
    path = workspace.judgments(DAY)
    data = json.loads(path.read_text(encoding="utf-8"))
    for m in data["memes"]:
        if m["meme_id"] == "pet-rock":
            m["override_reason"] = ""
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DataError, match="pet-rock"):
        pipeline.build(workspace, Settings(), DAY, render=False)


def test_scaffold_keeps_authored_fields_and_adds_facts(workspace):
    path = pipeline.write_scaffold(workspace, DAY)
    data = json.loads(path.read_text(encoding="utf-8"))
    original = json.loads((FIXTURE / "judgments.json").read_text(encoding="utf-8"))
    cat = next(m for m in data["memes"] if m["meme_id"] == "cat-ultra-bee")
    cat_orig = next(m for m in original["memes"] if m["meme_id"] == "cat-ultra-bee")
    assert cat["reason"] == cat_orig["reason"]
    assert "share" in cat["facts"]["hints"]
    pipeline.build(workspace, Settings(), DAY, render=False)  # a scaffold of a complete file still builds


def test_lark_records_convert_types_and_dedupe(workspace):
    schema = json.loads(workspace.lark_schema.read_text(encoding="utf-8"))
    table = next(t for t in schema["tables"] if t["key"] == "cc_rank_snapshot")
    rows = [{"capture_date": DAY, "region": "US", "period": 7, "rank": 3, "hashtag": "#x", "posts": 4700,
             "views": None, "industry": "News & Entertainment", "detail_id": "9", "detail_url": "https://a/9"}]
    (key, rec), = build_records(table, rows, ZoneInfo(schema["base_timezone"]))
    assert key == "2026-11-10|US|7日|3|#x"
    assert rec["周期"] == "7日" and rec["发帖数"] == 4700.0 and "播放量" not in rec
    assert rec["详情链接"] == {"link": "https://a/9", "text": "https://a/9"}
    assert isinstance(rec["抓取日期"], int)
