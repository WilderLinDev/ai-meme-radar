"""The agent-authored half of a day: `reports/YYYY-MM-DD/judgments.json`.

Only judgment lives here. Anything code can compute (total score, days hot,
peak status, share rate, Top 100 coverage, movement, backtest) is filled in by
`radar build`. The `facts` block that `radar scaffold` writes is read-only
context for the agent and is ignored on input.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .csvio import DataError
from .registry import norm_hashtag

Verdict = Literal["make", "watch", "skip"]
Part = Literal["main", "early"]
DIMENSIONS = ("heat", "trend", "share", "competition", "window")
DIMENSION_ZH = {"heat": "热度", "trend": "趋势", "share": "分享率", "competition": "竞争", "window": "窗口"}
VERDICT_ZH = {"make": "做", "watch": "观望", "skip": "不做"}
PLACEHOLDER = "TODO"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DimensionScore(_Strict):
    score: int = Field(ge=0, le=20)
    note: str = ""


class Scores(_Strict):
    heat: DimensionScore
    trend: DimensionScore
    share: DimensionScore
    competition: DimensionScore
    window: DimensionScore

    @property
    def total(self) -> int:
        return sum(getattr(self, d).score for d in DIMENSIONS)

    def short(self) -> str:
        return " ".join(f"{DIMENSION_ZH[d][0]}{getattr(self, d).score}" for d in DIMENSIONS)


class Link(_Strict):
    label: str
    url: str


class Competition(_Strict):
    capcut: str = ""
    capcut_url: str = ""
    sites: list[Link] = []
    judgment: str = ""


class HowTo(_Strict):
    play: list[str] = []
    user_input: str = ""
    tools: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    bgm: str = ""
    caption: str = ""
    hashtags: str = ""


class MemeJudgment(_Strict):
    meme_id: str
    part: Part = "main"
    verdict: Verdict
    override_reason: str = ""
    reason: str
    window_note: str = ""
    scores: Scores
    ignite_date: date | None = None
    ignite_note: str = ""
    what: str = ""
    origin: str = ""
    links: list[Link] = []
    heat_note: str = ""
    share_note: str = ""
    competition: Competition = Competition()
    howto: HowTo = HowTo()
    risks: list[str] = []
    watch_for: str = ""
    facts: dict[str, Any] | None = None  # scaffold context, ignored


class ExcludedGroup(_Strict):
    tags: list[str]
    reason: str

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return [norm_hashtag(t) for t in v]


class Judgments(_Strict):
    date: date
    memes: list[MemeJudgment]
    excluded_hashtags: list[ExcludedGroup] = []
    notes: list[str] = []
    unaccounted_hashtags: list[str] | None = None  # scaffold context, ignored

    @classmethod
    def load(cls, path: Path) -> "Judgments":
        try:
            return cls.model_validate_json(path.read_bytes())
        except ValidationError as e:
            raise DataError([f"{path.name}: {'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()])

    def excluded_tags(self) -> set[str]:
        return {t for g in self.excluded_hashtags for t in g.tags}
