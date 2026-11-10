"""D+3 backtest of every verdict in the tracker. Rules: docs/scoring.md.

- make: hit if the primary heat on D+3 is strictly above the D baseline, else miss.
  Only the first day of a make streak counts toward the hit rate.
- watch / skip: miss (a missed meme) if D+3 is at least 20% above baseline, else hit.
- pending: D+3 is after the as-of date. insufficient: no series, no baseline, or no D+3 point.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .analysis.primary import value_on
from .config import BACKTEST_HORIZON_DAYS, MISSED_RISE_THRESHOLD
from .csvio import write_rows
from .judgments import VERDICT_ZH
from .raw import History
from .registry import Registry
from .tracker import report_dates

Result = Literal["hit", "miss", "pending", "insufficient"]
RESULT_ZH = {
    "make": {"hit": "对", "miss": "错", "pending": "待定", "insufficient": "数据不足"},
    "watch": {"hit": "未漏判", "miss": "漏判", "pending": "待定", "insufficient": "数据不足"},
    "skip": {"hit": "未漏判", "miss": "漏判", "pending": "待定", "insufficient": "数据不足"},
}


class Evaluation(BaseModel):
    recommend_date: date
    meme_id: str
    name: str
    verdict: str
    total: int
    primary_metric: str
    baseline_date: date | None
    baseline_value: float | None
    d3_date: date
    d3_value: float | None
    result: Result
    counted: bool  # make only: first day of a streak
    note: str

    @property
    def result_zh(self) -> str:
        return RESULT_ZH[self.verdict][self.result]

    def line_zh(self) -> str:
        head = f"{self.recommend_date:%m-%d} 判{VERDICT_ZH[self.verdict]}，D+3（{self.d3_date:%m-%d}）{self.result_zh}"
        return f"{head}：{self.note}" if self.note else head


class Summary(BaseModel):
    as_of: date
    horizon_days: int = BACKTEST_HORIZON_DAYS
    missed_threshold: float = MISSED_RISE_THRESHOLD
    make_hit: int = 0
    make_miss: int = 0
    make_pending: int = 0
    make_insufficient: int = 0
    make_streak_repeats: int = 0
    other_hit: int = 0
    other_miss: int = 0
    other_pending: int = 0
    other_insufficient: int = 0

    @property
    def hit_rate(self) -> float | None:
        n = self.make_hit + self.make_miss
        return self.make_hit / n if n else None

    @property
    def missed_rate(self) -> float | None:
        n = self.other_hit + self.other_miss
        return self.other_miss / n if n else None

    def text_zh(self) -> str:
        hr = f"{self.hit_rate * 100:.0f}%" if self.hit_rate is not None else "暂无"
        mr = f"{self.missed_rate * 100:.0f}%" if self.missed_rate is not None else "暂无"
        return (f"截至 {self.as_of}，「做」命中率 {hr}（对 {self.make_hit} / 错 {self.make_miss}，"
                f"待定 {self.make_pending}，数据不足 {self.make_insufficient}，连续推荐不重复计 {self.make_streak_repeats}）。"
                f"观望/不做漏判率 {mr}（漏判 {self.other_miss} / 未漏判 {self.other_hit}，"
                f"待定 {self.other_pending}，数据不足 {self.other_insufficient}）。")


def _f(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def evaluate(rows: list[dict], registry: Registry, hist: History, as_of: date) -> tuple[list[Evaluation], Summary]:
    dates = report_dates(rows)
    by_key = {(r["date"], r["meme_id"]): r for r in rows}
    out: list[Evaluation] = []
    s = Summary(as_of=as_of)
    for r in sorted(rows, key=lambda r: (r["date"], r["meme_id"])):
        day = date.fromisoformat(r["date"])
        d3 = day + timedelta(days=BACKTEST_HORIZON_DAYS)
        verdict, metric = r["verdict"], r["primary_metric"]
        base_date = date.fromisoformat(r["primary_date"]) if r.get("primary_date") else None
        base = _f(r.get("primary_value"))
        idx = dates.index(r["date"])
        prev = by_key.get((dates[idx - 1], r["meme_id"])) if idx > 0 else None
        counted = verdict == "make" and not (prev and prev["verdict"] == "make")

        d3_value = None
        if d3 > as_of:
            result, note = "pending", ""
        elif metric == "none" or r["meme_id"] not in registry:
            result, note = "insufficient", "没有可回测的全站日序列"
        elif base_date is None or base is None:
            result, note = "insufficient", "推荐日没有主热度基线"
        else:
            meme = registry[r["meme_id"]].model_copy(update={"primary_metric": metric})
            pair = value_on(meme, hist, base_date, d3)
            if pair is None:
                result, note = "insufficient", f"没有 {d3:%m-%d} 的完整主热度点"
            else:
                base, d3_value = pair
                if verdict == "make":
                    result = "hit" if d3_value > base else "miss"
                else:
                    result = "miss" if base > 0 and d3_value >= base * (1 + MISSED_RISE_THRESHOLD) else "hit"
                note = f"基线 {base_date:%m-%d} 的 {base:g} → {d3:%m-%d} 的 {d3_value:g}"

        ev = Evaluation(recommend_date=day, meme_id=r["meme_id"], name=r["name"], verdict=verdict,
                        total=int(r["total"]), primary_metric=metric, baseline_date=base_date,
                        baseline_value=base, d3_date=d3, d3_value=d3_value, result=result,
                        counted=counted, note=note)
        out.append(ev)
        if verdict == "make":
            if not counted:
                s.make_streak_repeats += 1
            else:
                setattr(s, f"make_{result}", getattr(s, f"make_{result}") + 1)
        else:
            setattr(s, f"other_{result}", getattr(s, f"other_{result}") + 1)
    return out, s


def latest_line(evals: list[Evaluation], meme_id: str, before: date) -> str:
    """The most recent settled evaluation of a meme from an earlier report, for its card."""
    past = [e for e in evals if e.meme_id == meme_id and e.recommend_date < before]
    settled = [e for e in past if e.result in ("hit", "miss")]
    pick = max(settled or past, key=lambda e: e.recommend_date, default=None)
    return pick.line_zh() if pick else "首次出现，暂无回测"


CSV_COLUMNS = list(Evaluation.model_fields)


def write(evals: list[Evaluation], summary: Summary, json_path: Path, csv_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": summary.model_dump(mode="json") | {"hit_rate": summary.hit_rate,
                                                      "missed_rate": summary.missed_rate,
                                                      "text_zh": summary.text_zh()},
        "evaluations": [e.model_dump(mode="json") for e in evals],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_rows(csv_path, CSV_COLUMNS, [e.model_dump(mode="json") for e in evals])
