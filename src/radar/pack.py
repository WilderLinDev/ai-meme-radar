"""Compute facts, then merge them with judgments into the meme pack.

The meme pack (`reports/YYYY-MM-DD/meme-pack.json`) is the single source of a
day's decision. Every report is rendered from it. See docs/adr/0001.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel

from .analysis import cc as cc_analysis
from .analysis.cc import CCPresence
from .analysis.lifecycle import classify
from .analysis.primary import METRIC_ZH, primary_points
from .analysis.share import ShareStats, share_stats
from .backtest import Summary
from .config import CC_PERIODS, CC_REGIONS
from .judgments import ExcludedGroup, Judgments, MemeJudgment, Verdict
from .raw import History, RawDay
from .raw.schemas import CCAudience, Gap, Remix
from .registry import Meme
from .scoring import heat_hint, share_hint, suggested_verdict, trend_hint


class Movement(BaseModel):
    prev_date: date
    prev_total: int
    prev_verdict: str


class Facts(BaseModel):
    name: str
    name_zh: str
    display: str
    primary_metric: str
    primary_label: str
    primary_value: float | None = None
    primary_date: date | None = None
    peak_status: str
    peak_label: str
    peak_drop: float | None = None
    share: list[ShareStats] = []
    cc: list[CCPresence] = []
    source_label: str = ""
    audience: list[CCAudience] = []
    top_remixes: list[Remix] = []
    watchlist_handles: list[str] = []
    movement: Movement | None = None
    hints: dict[str, str] = {}
    # filled once judgments and history are known
    days_hot: int | None = None
    total: int | None = None
    suggested_verdict: Verdict | None = None
    backtest_line: str = ""

    @property
    def tiktok_share(self) -> ShareStats | None:
        return next((s for s in self.share if s.platform == "TikTok"), None)


class PackMeme(BaseModel):
    judgment: MemeJudgment
    facts: Facts

    @property
    def id(self) -> str:
        return self.judgment.meme_id


class Pack(BaseModel):
    date: date
    memes: list[PackMeme]
    excluded_hashtags: list[ExcludedGroup] = []
    notes: list[str] = []
    gaps: list[Gap] = []
    cc_lists: list[str] = []  # region/period lists captured today, e.g. "US·7日"
    backtest: Summary | None = None

    def ranked(self, part: str | None = None) -> list[PackMeme]:
        ms = [m for m in self.memes if part is None or m.judgment.part == part]
        return sorted(ms, key=lambda m: (-(m.facts.total or 0), m.facts.name))

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Pack":
        return cls.model_validate_json(path.read_bytes())


def compute_facts(meme: Meme, raw: RawDay, hist: History, tracker_prev: dict | None) -> Facts:
    day = raw.day
    pts = primary_points(meme, hist, day)
    life = classify(pts)
    remixes = [r for r in raw.remixes if r.meme_id == meme.id]
    share = share_stats(remixes)
    cells = cc_analysis.presence(raw.cc_top100, meme.cc_hashtags)
    tiktok = next((s for s in share if s.platform == "TikTok"), None)

    vr = [p for p in hist.series(meme.id, "viralremix_new_videos") if p.complete and p.date <= day]
    x7 = [p for p in hist.series(meme.id, "x_posts")
          if p.complete and day - timedelta(days=6) <= p.date <= day]
    movement = None
    if tracker_prev:
        movement = Movement(prev_date=date.fromisoformat(tracker_prev["date"]),
                            prev_total=int(tracker_prev["total"]), prev_verdict=tracker_prev["verdict"])
    return Facts(
        name=meme.name, name_zh=meme.name_zh, display=meme.display,
        primary_metric=meme.primary_metric, primary_label=METRIC_ZH[meme.primary_metric],
        primary_value=pts[-1].value if pts else None, primary_date=pts[-1].date if pts else None,
        peak_status=life.status, peak_drop=life.drop,
        peak_label="没有全站日序列，不判断" if meme.primary_metric == "none" else life.label_zh,
        share=share, cc=cells, source_label=cc_analysis.source_label(cells),
        audience=[a for a in raw.cc_audience if a.hashtag in meme.cc_hashtags],
        top_remixes=sorted(remixes, key=lambda r: -(r.views or 0))[:10],
        watchlist_handles=sorted({f"{p.platform}@{p.handle}" for p in raw.watchlist_posts if p.meme_id == meme.id}),
        movement=movement,
        hints={
            "heat": heat_hint(vr[-1].value if vr else None, sum(p.value for p in x7) if x7 else None),
            "trend": trend_hint(life.status, life.drop),
            "share": share_hint(tiktok.median if tiktok else None, bool(tiktok and tiktok.enough)),
        },
    )


def finish_facts(f: Facts, j: MemeJudgment, day: date) -> Facts:
    f.total = j.scores.total
    f.suggested_verdict = suggested_verdict(j.scores)
    f.days_hot = (day - j.ignite_date).days if j.ignite_date else None
    return f


def day_gaps(raw: RawDay) -> tuple[list[Gap], list[str]]:
    gaps = list(raw.gaps)
    gaps += [Gap(source=f, note="今天没有这份文件") for f in raw.missing_files]
    have = {(r.region, r.period) for r in raw.cc_top100}
    lists = [f"{reg}·{per}日" for reg in CC_REGIONS for per in CC_PERIODS if (reg, per) in have]
    missing = [f"{reg}·{per}日" for reg in CC_REGIONS for per in CC_PERIODS if (reg, per) not in have]
    if raw.cc_top100 and missing:
        gaps.append(Gap(source="cc-top100.csv", note="缺少这些榜：" + "、".join(missing)))
    return gaps, lists


def coverage_problems(j: Judgments, registry_tags: dict[str, str], raw: RawDay) -> list[str]:
    judged = {m.meme_id for m in j.memes}
    linked = {t for t, mid in registry_tags.items() if mid in judged}
    left = cc_analysis.unaccounted(raw.cc_top100, linked, j.excluded_tags())
    if not left:
        return []
    return [f"{len(left)} Top 100 hashtags are neither linked to a judged meme nor in excluded_hashtags: "
            + ", ".join("#" + t for t in left[:30]) + (" …" if len(left) > 30 else "")]


def scaffold(existing: Judgments | None, day: date, candidates: list[Meme], facts: dict[str, Facts],
             unaccounted: list[str]) -> dict:
    """A judgments.json draft: authored fields kept, facts refreshed, new candidates added."""
    keep = {m.meme_id: m for m in (existing.memes if existing else [])}
    memes = []
    for meme in candidates:
        if meme.id in keep:
            d = keep[meme.id].model_dump(mode="json")
        else:
            d = MemeJudgment(
                meme_id=meme.id, verdict="skip", reason="TODO",
                scores={k: {"score": 0, "note": "TODO"} for k in ("heat", "trend", "share", "competition", "window")},
            ).model_dump(mode="json")
        d["facts"] = facts[meme.id].model_dump(mode="json", include={
            "display", "primary_label", "primary_value", "primary_date", "peak_label",
            "share", "source_label", "watchlist_handles", "movement", "hints"})
        memes.append(d)
    excluded = [g.model_dump() for g in (existing.excluded_hashtags if existing else [])]
    if unaccounted:
        excluded.append({"tags": unaccounted, "reason": "TODO：分组写排除理由；适合做梗的话题改为登记成梗"})
    return {
        "date": day.isoformat(),
        "memes": memes,
        "excluded_hashtags": excluded,
        "notes": existing.notes if existing else [],
    }
