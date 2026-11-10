"""Creative Center Top 100 coverage per meme, and the coverage check."""
from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from ..raw.schemas import CCRank


class CCPresence(BaseModel):
    hashtag: str
    region: str
    rank_7d: int | None = None
    rank_30d: int | None = None
    posts_7d: int | None = None
    views_7d: int | None = None
    posts_30d: int | None = None
    views_30d: int | None = None

    @property
    def flag(self) -> str:
        """7-day vs 30-day presence proxy (Creative Center rank_change is often blank)."""
        if self.rank_7d and self.rank_30d:
            return "SUSTAIN"
        return "NEW_7D" if self.rank_7d else "FADE_30D"


def presence(rows: list[CCRank], hashtags: list[str]) -> list[CCPresence]:
    wanted = set(hashtags)
    cells: dict[tuple[str, str], CCPresence] = {}
    for r in rows:
        if r.hashtag not in wanted:
            continue
        cell = cells.setdefault((r.hashtag, r.region), CCPresence(hashtag=r.hashtag, region=r.region))
        if r.period == 7:
            cell.rank_7d, cell.posts_7d, cell.views_7d = r.rank, r.posts, r.views
        else:
            cell.rank_30d, cell.posts_30d, cell.views_30d = r.rank, r.posts, r.views
    return sorted(cells.values(), key=lambda c: (hashtags.index(c.hashtag), c.region))


def source_label(cells: list[CCPresence]) -> str:
    regions = sorted({c.region for c in cells})
    return f"TikTok Top100·{','.join(regions)}" if regions else ""


def unaccounted(rows: list[CCRank], linked: set[str], excluded: set[str]) -> list[str]:
    """Top 100 hashtags that are neither linked to a judged meme nor excluded with a reason."""
    best: dict[str, int] = defaultdict(lambda: 10**9)
    for r in rows:
        best[r.hashtag] = min(best[r.hashtag], r.rank)
    left = [t for t in best if t not in linked and t not in excluded]
    return sorted(left, key=lambda t: (best[t], t))
