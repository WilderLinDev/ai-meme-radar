from __future__ import annotations

from datetime import date

import pytest

from radar.analysis.lifecycle import Point, classify
from radar.analysis.share import share_stats
from radar.csvio import DataError, read_rows
from radar.judgments import Scores
from radar.raw.schemas import CCRank, Remix, parse_count
from radar.registry import Meme, Registry
from radar.scoring import suggested_verdict


def d(day: int) -> date:
    return date(2026, 11, day)


@pytest.mark.parametrize("raw,expected", [("4.7K", 4700), ("1.2M", 1_200_000), ("12,345", 12345), ("3B", 3_000_000_000)])
def test_parse_count(raw, expected):
    assert parse_count(raw) == expected


def test_parse_count_rejects_text():
    with pytest.raises(ValueError):
        parse_count("lots")


def test_bad_rows_are_all_reported_with_line_numbers(tmp_path):
    p = tmp_path / "cc-top100.csv"
    p.write_text("region,period,rank,hashtag\nUS,7,1,#a\nNL,7,2,#b\nUS,14,3,#c\n", encoding="utf-8")
    with pytest.raises(DataError) as e:
        read_rows(p, CCRank)
    assert len(e.value.problems) == 2
    assert e.value.problems[0].startswith("cc-top100.csv:3")


def _meme(id, **kw):
    return Meme(id=id, name=id, primary_metric=kw.pop("primary_metric", "none"), first_seen="2026-11-10", **kw)


def test_registry_rejects_shared_hashtag_and_unknown_id():
    with pytest.raises(DataError):
        Registry([_meme("a", cc_hashtags="x"), _meme("b", cc_hashtags="#X")])
    reg = Registry([_meme("a")])
    with pytest.raises(DataError):
        reg.require(["a", "ghost"], "test")


def test_registry_cc_metric_needs_region():
    with pytest.raises(DataError):
        Registry([_meme("a", cc_hashtags="x", primary_metric="cc_index_30d")])


def test_registry_ids_are_kebab_case():
    with pytest.raises(ValueError):
        _meme("Shoulder Carry")


@pytest.mark.parametrize("values,status", [
    ([10, 20, 30], "rising"),
    ([10, 30, 30], "peak"),
    ([10, 100, 90], "near_peak"),
    ([10, 100, 50], "declining"),
    ([10], "unknown"),
])
def test_lifecycle(values, status):
    assert classify([Point(d(i + 1), v) for i, v in enumerate(values)]).status == status


def test_share_stats_per_platform_and_min_n():
    rows = [Remix(meme_id="m", link=f"l{i}", platform="TikTok", views=1000, shares=10 * (i + 1)) for i in range(5)]
    rows.append(Remix(meme_id="m", link="x", platform="X", views=1000, shares=500))
    tiktok, x = share_stats(rows)
    assert tiktok.platform == "TikTok" and tiktok.enough and tiktok.median == pytest.approx(0.03)
    assert x.platform == "X" and not x.enough


def _scores(heat, trend, share, comp, window):
    return Scores.model_validate({k: {"score": v} for k, v in
                                  zip(("heat", "trend", "share", "competition", "window"), (heat, trend, share, comp, window))})


def test_suggested_verdict_thresholds():
    assert suggested_verdict(_scores(13, 13, 13, 13, 13)) == "make"   # 65, window 13
    assert suggested_verdict(_scores(15, 15, 15, 15, 9)) == "watch"   # 69 but window < 10
    assert suggested_verdict(_scores(9, 9, 9, 9, 9)) == "watch"       # 45
    assert suggested_verdict(_scores(8, 9, 9, 9, 9)) == "skip"        # 44


def test_dimension_score_range():
    with pytest.raises(ValueError):
        _scores(21, 0, 0, 0, 0)
