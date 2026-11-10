# -*- coding: utf-8 -*-
"""Load remix-video share-rate samples and roll them up per meme.

CSV columns (minimum):
  meme, link, platform, creator, date, views, likes, shares, comments, saves, is_AI
Optional: in_top_sample (yes/no), share_rate, like_rate, shares_per_like, verified, source, notes

Share rate = shares / views. Like rate = likes / views.
TikTok shares and X reposts are never mixed in one median.
If a platform group has fewer than MIN_N readable remixes, verdict is 样本不足.
"""
from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

MIN_N = 5

# substring (lowercase) -> canonical CSV meme key
ALIASES = [
    ("bicep", "Bicep Heart"),
    ("malfoid", "Malfoid"),
    ("ba ba ba", "Ba Ba Ba Dance"),
    ("shoulder", "Shoulder Carry"),
    ("can i ride", "Can I Ride"),
    ("flamingo", "Flamingo Float"),
    ("grandpa", "Grandpa Fish"),
    ("切鱼", "Grandpa Fish"),
    ("ultra bee", "Cat on Ultra Bee"),
    ("cat on", "Cat on Ultra Bee"),
    ("then i walk", "Then I Walk In"),
    ("walk in", "Then I Walk In"),
    ("shaking head", "Shaking Head"),
    ("摇头", "Shaking Head"),
]

NICK = {
    "Bicep Heart": "Bicep Heart",
    "Malfoid": "Malfoid",
    "Ba Ba Ba Dance": "Ba Ba Ba",
    "Shoulder Carry": "Shoulder Carry",
    "Can I Ride": "Can I Ride",
    "Flamingo Float": "Flamingo",
    "Grandpa Fish": "切鱼梗",
    "Cat on Ultra Bee": "Cat Ultra Bee",
    "Then I Walk In": "Then I Walk In",
    "Shaking Head": "宠物摇头",
}


def canonical_meme(name: str) -> str:
    low = (name or "").lower()
    for key, canon in ALIASES:
        if key in low:
            return canon
    return (name or "").strip()


def pct(x, digits=2) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.{digits}f}%"


def _to_int(v):
    if v is None or v == "":
        return 0
    try:
        return int(float(str(v).replace(",", "").strip()))
    except ValueError:
        return 0


@dataclass
class RemixVideo:
    meme: str
    link: str
    platform: str
    creator: str
    date: str
    views: int
    likes: int
    shares: int
    comments: int
    saves: int
    is_ai: str
    in_top_sample: bool
    verified: str = "已核实"
    notes: str = ""

    @property
    def share_rate(self) -> float:
        return (self.shares / self.views) if self.views else 0.0

    @property
    def like_rate(self) -> float:
        return (self.likes / self.views) if self.views else 0.0

    @property
    def shares_per_like(self) -> float | None:
        return (self.shares / self.likes) if self.likes else None


@dataclass
class MemeRemixStats:
    meme: str
    platform: str
    n: int
    median_share: float | None
    weighted_share: float | None
    median_like: float | None
    weighted_like: float | None
    median_share_like: float | None
    median_views: float | None
    verdict: str
    videos: list = field(default_factory=list)

    @property
    def enough(self) -> bool:
        return self.n >= MIN_N and self.median_share is not None

    def summary_zh(self) -> str:
        if not self.enough:
            return f"{self.platform} 样本不足（可读二创 n={self.n}，需至少 {MIN_N}）"
        return (
            f"{self.platform} 中位分享率 {pct(self.median_share)}，"
            f"加权 {pct(self.weighted_share)}，"
            f"中位点赞率 {pct(self.median_like)}（n={self.n}）【已核实】"
        )


def _auto_verdict(n, median_share) -> str:
    if n < MIN_N or median_share is None:
        return "样本不足"
    if median_share >= 0.02:
        return "高分享，格式更易被转发出去"
    if median_share >= 0.01:
        return "中高分享"
    if median_share >= 0.006:
        return "中等分享"
    return "分享偏低（更偏完播/点赞，少转发）"


def load_remix_csv(path) -> list[RemixVideo]:
    path = Path(path)
    videos = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            views = _to_int(row.get("views"))
            if views <= 0:
                continue
            flag = str(row.get("in_top_sample") or "yes").strip().lower()
            videos.append(RemixVideo(
                meme=canonical_meme(row.get("meme") or ""),
                link=(row.get("link") or "").strip(),
                platform=(row.get("platform") or "TikTok").strip(),
                creator=(row.get("creator") or "").lstrip("@"),
                date=(row.get("date") or "").strip(),
                views=views,
                likes=_to_int(row.get("likes")),
                shares=_to_int(row.get("shares")),
                comments=_to_int(row.get("comments")),
                saves=_to_int(row.get("saves")),
                is_ai=(row.get("is_AI") or row.get("is_ai") or "unclear").strip().lower(),
                in_top_sample=flag in {"", "yes", "y", "1", "true"},
                verified=(row.get("verified") or "已核实").strip(),
                notes=(row.get("notes") or "").strip(),
            ))
    return videos


def summarize_remixes(videos: list[RemixVideo]) -> dict[str, dict[str, MemeRemixStats]]:
    """Return {canonical_meme: {platform: MemeRemixStats}} using in_top_sample rows."""
    groups = defaultdict(lambda: defaultdict(list))
    for v in videos:
        if v.in_top_sample:
            groups[v.meme][v.platform].append(v)
    out = {}
    for meme, plats in groups.items():
        out[meme] = {}
        for platform, items in plats.items():
            items = sorted(items, key=lambda x: -x.views)
            rates = [x.share_rate for x in items]
            likes = [x.like_rate for x in items]
            sl = [x.shares_per_like for x in items if x.shares_per_like is not None]
            tot_v = sum(x.views for x in items)
            tot_s = sum(x.shares for x in items)
            tot_l = sum(x.likes for x in items)
            n = len(items)
            med = statistics.median(rates) if rates else None
            out[meme][platform] = MemeRemixStats(
                meme=meme,
                platform=platform,
                n=n,
                median_share=med,
                weighted_share=(tot_s / tot_v) if tot_v else None,
                median_like=statistics.median(likes) if likes else None,
                weighted_like=(tot_l / tot_v) if tot_v else None,
                median_share_like=statistics.median(sl) if sl else None,
                median_views=statistics.median([x.views for x in items]) if items else None,
                verdict=_auto_verdict(n, med),
                videos=items,
            )
    return out


def stats_for(summary: dict, name: str, platform: str = "TikTok") -> MemeRemixStats | None:
    key = canonical_meme(name)
    return (summary.get(key) or {}).get(platform)


def tiktok_points(summary: dict) -> list[MemeRemixStats]:
    pts = []
    for meme, plats in summary.items():
        st = plats.get("TikTok")
        if st and st.enough:
            pts.append(st)
    return pts
