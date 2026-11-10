"""Row schemas for raw snapshots in `data/raw/YYYY-MM-DD/`.

One file per source kind. The agent writes them during collection; `radar
ingest` validates them. Counts may be written the way the page shows them
("4.7K", "1.2M", "12,345").
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, field_validator

from ..config import CC_REGIONS
from ..registry import norm_hashtag

_SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9}


def parse_count(v):
    if v is None or isinstance(v, (int, float)):
        return v
    s = str(v).strip().replace(",", "").upper()
    if not s:
        return None
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*([KMB]?)", s)
    if not m:
        raise ValueError(f"not a count: {v!r}")
    return int(round(float(m.group(1)) * _SUFFIX.get(m.group(2), 1)))


def parse_bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y"}:
        return True
    if s in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"not a boolean: {v!r}")


def _period(v):
    v = int(v)
    if v not in (7, 30):
        raise ValueError("period must be 7 or 30")
    return v


Count = Annotated[int | None, BeforeValidator(parse_count)]
Period = Annotated[int, BeforeValidator(_period)]
Flag = Annotated[bool, BeforeValidator(parse_bool)]
Region = Literal[CC_REGIONS]  # type: ignore[valid-type]


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Tagged(_Row):
    hashtag: str

    @field_validator("hashtag")
    @classmethod
    def _tag(cls, v: str) -> str:
        return norm_hashtag(v)


class CCRank(_Tagged):
    """One row of a Creative Center Top 100 list."""
    region: Region
    period: Period
    rank: int
    rank_change: int | None = None
    is_new: Flag = False
    posts: Count = None
    views: Count = None
    industry: str = "News & Entertainment"
    detail_id: str = ""


class CCCurvePoint(_Tagged):
    """One day of a hashtag detail-page popularity curve (0-100, per-window)."""
    region: Region
    period: Period
    date: date
    value: float
    detail_id: str = ""


class CCAudience(_Tagged):
    """One audience bucket from a hashtag detail page."""
    region: Region
    period: Period
    dimension: Literal["age", "country", "interest"]
    bucket: str
    value: float
    unit: Literal["pct", "index"]


class HeatPoint(_Row):
    """One day of a meme's heat series (X posts, ViralRemix new videos, ...)."""
    meme_id: str
    date: date
    metric: str
    value: float
    source: str = ""
    complete: Flag = True


class Remix(_Row):
    """One high-view remix (never the original)."""
    meme_id: str
    link: str
    platform: str
    creator: str = ""
    posted_on: date | None = None
    views: Count
    likes: Count = None
    shares: Count = None
    comments: Count = None
    saves: Count = None
    is_ai: Literal["yes", "no", "unclear"] = "unclear"

    @property
    def share_rate(self) -> float | None:
        if not self.views or self.shares is None:
            return None
        return self.shares / self.views


class WatchlistPost(_Row):
    """One post from a watchlist account in the last 48h."""
    platform: str
    handle: str
    link: str
    posted_on: date | None = None
    caption: str = ""
    views: Count = None
    likes: Count = None
    meme_id: str = ""
    is_template: Flag = False
    is_ai_effect: Flag = False


class Gap(_Row):
    """Something that should have been collected today but was not."""
    source: str
    note: str


RAW_FILES: dict[str, type[_Row]] = {
    "cc-top100.csv": CCRank,
    "cc-curves.csv": CCCurvePoint,
    "cc-audience.csv": CCAudience,
    "heat.csv": HeatPoint,
    "remixes.csv": Remix,
    "watchlist-posts.csv": WatchlistPost,
}
