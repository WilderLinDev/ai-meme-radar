from __future__ import annotations

from datetime import date

from radar.backtest import evaluate
from radar.raw import History
from radar.raw.schemas import CCCurvePoint, HeatPoint
from radar.registry import Meme, Registry


def d(day: int) -> date:
    return date(2026, 11, day)


REG = Registry([
    Meme(id="up", name="Up", primary_metric="x_posts", first_seen=d(1)),
    Meme(id="down", name="Down", primary_metric="x_posts", first_seen=d(1)),
    Meme(id="flat", name="Flat", primary_metric="none", first_seen=d(1)),
    Meme(id="cc", name="CC", primary_metric="cc_index_30d", cc_hashtags=["tag"], primary_region="US", first_seen=d(1)),
])


def row(day, meme_id, verdict, value="", value_date="", metric=None):
    return {"date": d(day).isoformat(), "meme_id": meme_id, "name": meme_id, "verdict": verdict, "total": "60",
            "primary_metric": metric or REG[meme_id].primary_metric, "primary_value": value,
            "primary_date": d(value_date).isoformat() if value_date else ""}


def hist_with(points: dict[str, dict[int, float]], curves: dict[int, dict[int, float]] | None = None) -> History:
    h = History(until=d(30))
    for meme_id, series in points.items():
        h.heat[(meme_id, "x_posts")] = {d(k): HeatPoint(meme_id=meme_id, date=d(k), metric="x_posts", value=v)
                                        for k, v in series.items()}
    for cap, series in (curves or {}).items():
        h.cc_curves[d(cap)] = [CCCurvePoint(hashtag="tag", region="US", period=30, date=d(k), value=v)
                               for k, v in series.items()]
    return h


def test_make_hit_miss_pending_insufficient():
    rows = [row(2, "up", "make", "10", 2), row(2, "down", "make", "10", 2), row(2, "flat", "make"),
            row(9, "up", "make", "30", 9)]
    h = hist_with({"up": {2: 10, 5: 20, 9: 30}, "down": {2: 10, 5: 10}})
    evals, s = evaluate(rows, REG, h, as_of=d(10))
    res = {(e.recommend_date.day, e.meme_id): e.result for e in evals}
    assert res[(2, "up")] == "hit"
    assert res[(2, "down")] == "miss"  # equal is not a rise
    assert res[(2, "flat")] == "insufficient"
    assert res[(9, "up")] == "pending"
    assert s.hit_rate == 0.5


def test_streak_counts_first_day_only():
    rows = [row(2, "up", "make", "10", 2), row(3, "up", "make", "12", 3), row(4, "up", "watch", "13", 4),
            row(5, "up", "make", "14", 5)]
    h = hist_with({"up": {2: 10, 3: 12, 4: 13, 5: 14, 6: 15, 8: 20}})
    evals, s = evaluate(rows, REG, h, as_of=d(10))
    counted = [e.recommend_date.day for e in evals if e.counted]
    assert counted == [2, 5]
    assert s.make_streak_repeats == 1


def test_watch_and_skip_count_as_missed_when_rising_20_percent():
    rows = [row(2, "up", "skip", "10", 2), row(2, "down", "watch", "10", 2)]
    h = hist_with({"up": {2: 10, 5: 12}, "down": {2: 10, 5: 11.9}})
    evals, s = evaluate(rows, REG, h, as_of=d(10))
    res = {e.meme_id: e.result for e in evals}
    assert res == {"up": "miss", "down": "hit"}
    assert s.missed_rate == 0.5


def test_cc_index_compares_within_one_capture():
    rows = [row(2, "cc", "make", "80", 2)]
    # capture 6 contains both day 2 and day 5; capture 7 only has day 5 (re-normalised higher)
    h = hist_with({}, curves={6: {2: 90, 5: 60}, 7: {5: 100}})
    evals, _ = evaluate(rows, REG, h, as_of=d(10))
    assert evals[0].result == "miss"
    assert (evals[0].baseline_value, evals[0].d3_value) == (90, 60)
