"""Remix share rate (shares / views), per platform. Platforms are never mixed."""
from __future__ import annotations

import statistics
from collections import defaultdict

from pydantic import BaseModel

from ..config import SHARE_MIN_N
from ..raw.schemas import Remix


class ShareStats(BaseModel):
    platform: str
    n: int
    median: float | None
    weighted: float | None
    median_views: float | None

    @property
    def enough(self) -> bool:
        return self.n >= SHARE_MIN_N and self.median is not None

    @property
    def label_zh(self) -> str:
        if not self.enough:
            return f"{self.platform} 样本不足（n={self.n}，至少需要 {SHARE_MIN_N}）"
        return (f"{self.platform} 中位分享率 {self.median * 100:.2f}%，"
                f"播放加权 {self.weighted * 100:.2f}%（n={self.n}）【已核实】")


def share_stats(remixes: list[Remix]) -> list[ShareStats]:
    by_platform: dict[str, list[Remix]] = defaultdict(list)
    for r in remixes:
        if r.share_rate is not None:
            by_platform[r.platform].append(r)
    out = []
    for platform, rows in sorted(by_platform.items(), key=lambda kv: (kv[0] != "TikTok", kv[0])):
        views = sum(r.views or 0 for r in rows)
        out.append(ShareStats(
            platform=platform,
            n=len(rows),
            median=statistics.median(r.share_rate for r in rows),
            weighted=(sum(r.shares or 0 for r in rows) / views) if views else None,
            median_views=statistics.median(r.views or 0 for r in rows),
        ))
    return out
