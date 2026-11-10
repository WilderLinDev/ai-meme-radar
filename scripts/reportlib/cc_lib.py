# -*- coding: utf-8 -*-
"""Creative Center CSV parsing, classification, and derived signals."""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

BUCKET_ORDER = [
    "美国中期选举/政治",
    "节日季",
    "影视/IP/明星",
    "TikTok官方活动/直播/创作者激励",
    "音乐/DJ",
    "情感/故事类",
    "梗/挑战/可二创格式",
    "其他/非英语",
]

# Explicit overrides beat keyword rules. Keys are lowercased hashtags.
OVERRIDES = {
    "#blue": "美国中期选举/政治",
    "#wedidit": "美国中期选举/政治",
    "#fdt": "美国中期选举/政治",
    "#november3rd": "美国中期选举/政治",
    "#abdul": "美国中期选举/政治",
    "#abdulelsayed": "美国中期选举/政治",
    "#talafreako": "美国中期选举/政治",
    "#bobbypulido": "美国中期选举/政治",
    "#mackgeiger": "美国中期选举/政治",
    "#johnanderson": "美国中期选举/政治",
    "#ilhanomar": "美国中期选举/政治",
    "#yourvotematters": "美国中期选举/政治",
    "#trumpsupporters": "美国中期选举/政治",
    "#earlyvoting": "美国中期选举/政治",
    "#voting": "美国中期选举/政治",
    "#votingday": "美国中期选举/政治",
    "#lastchristmas": "节日季",
    "#veteransday": "节日季",
    "#nnn": "节日季",
    "#снег": "节日季",
    "#scorpioseason": "节日季",
    "#winter2025": "节日季",
    "#daylightsavings": "节日季",
    "#timechange": "节日季",
    "#november1st": "节日季",
    "#november": "节日季",
    "#noviembre": "节日季",
    "#happydiwali": "节日季",
    "#tihar": "节日季",
    "#dashain": "节日季",
    "#halloweentransition": "节日季",
    "#хеллоуин": "节日季",
    "#хэллоуин": "节日季",
    "#littleredridinghood": "节日季",
    "#tiktokscaryhorrorcontest": "TikTok官方活动/直播/创作者激励",
    "#tiktokthrillermysterycontest": "TikTok官方活动/直播/创作者激励",
    "#livecanbeeasy": "TikTok官方活动/直播/创作者激励",
    "#livemonetization": "TikTok官方活动/直播/创作者激励",
    "#mylivejourney": "TikTok官方活动/直播/创作者激励",
    "#livefest2026": "TikTok官方活动/直播/创作者激励",
    "#aniimocreator": "TikTok官方活动/直播/创作者激励",
    "#asktiktok": "TikTok官方活动/直播/创作者激励",
    "#asktiktoktako": "TikTok官方活动/直播/创作者激励",
    "#iwanttogoviralontiktok2026": "TikTok官方活动/直播/创作者激励",
    "#stickerbanner": "梗/挑战/可二创格式",
    "#coderot": "梗/挑战/可二创格式",
    "#imsosorry": "梗/挑战/可二创格式",
    "#captainsaveaho": "梗/挑战/可二创格式",
    "#damehombro": "梗/挑战/可二创格式",
    "#findyourman": "梗/挑战/可二创格式",
    "#nosabo": "梗/挑战/可二创格式",
    "#nosabokid": "梗/挑战/可二创格式",
    "#nosabokids": "梗/挑战/可二创格式",
    "#youcanseeeverything": "影视/IP/明星",
    "#loozecannon": "影视/IP/明星",
    "#loozecannon1": "影视/IP/明星",
    "#bigmichaelmichael": "影视/IP/明星",
    "#bigmichael": "影视/IP/明星",
    "#transformers": "影视/IP/明星",
    "#godzillaminuszero": "影视/IP/明星",
    "#godzillaminusone": "影视/IP/明星",
    "#godzilla": "影视/IP/明星",
    "#strangerthingsday": "影视/IP/明星",
    "#clayface": "影视/IP/明星",
    "#visionquest": "影视/IP/明星",
    "#georgieandmandysfirstmarriage": "影视/IP/明星",
    "#brandrisk": "影视/IP/明星",
    "#acosh": "影视/IP/明星",
    "#talkingtom": "影视/IP/明星",
    "#conformitygate": "影视/IP/明星",
    "#disneynight": "影视/IP/明星",
    "#calvinklein": "影视/IP/明星",
    "#housewife": "影视/IP/明星",
    "#catwoman": "影视/IP/明星",
    "#greysanatomyedit": "影视/IP/明星",
    "#patrickstewart": "影视/IP/明星",
    "#ethanklein": "影视/IP/明星",
    "#h3h3": "影视/IP/明星",
    "#h3": "影视/IP/明星",
    "#bellaramsey": "影视/IP/明星",
    "#rjmitte": "影视/IP/明星",
    "#vsfashionshow": "影视/IP/明星",
    "#victoriassecretfashionshow": "影视/IP/明星",
    "#victoriasecretfashionshow": "影视/IP/明星",
    "#victoriassecret": "影视/IP/明星",
    "#2chainz": "影视/IP/明星",
    "#usher": "影视/IP/明星",
    "#marcel": "影视/IP/明星",
    "#holywar": "影视/IP/明星",
    "#luckicomplexcon": "影视/IP/明星",
    "#ashtrivinovsbri": "影视/IP/明星",
    "#angelofmydreams": "音乐/DJ",
    "#beautyschooldropout": "音乐/DJ",
    "#dj": "音乐/DJ",
    "#djremix": "音乐/DJ",
    "#rnbtour": "音乐/DJ",
    "#calvinharris": "音乐/DJ",
    "#alecbenjamin": "音乐/DJ",
    "#rechazame": "音乐/DJ",
    "#sicknewworld": "音乐/DJ",
    "#iiipoints": "音乐/DJ",
    "#edcorlando": "音乐/DJ",
    "#missingsomeone": "情感/故事类",
    "#hiddenpain": "情感/故事类",
    "#relationshipstory": "情感/故事类",
    "#couplestory": "情感/故事类",
    "#secretstory": "情感/故事类",
    "#pettytiktok": "情感/故事类",
    "#rumor": "情感/故事类",
    "#mybest": "情感/故事类",
    "#crushtok": "情感/故事类",
    "#xycbca": "其他/非英语",
    "#sema": "其他/非英语",
    "#edco": "其他/非英语",
    "#hank": "其他/非英语",
    "#palmbay": "其他/非英语",
    "#tenerife": "其他/非英语",
    "#cnnbrasil": "其他/非英语",
    "#sãopaulo": "其他/非英语",
    "#natriavpn": "其他/非英语",
    "#yorkshirewildlifepark": "其他/非英语",
    "#ghoe": "其他/非英语",
}

POLITICAL_KEYS = (
    "election", "vote", "midterm",
    "democrat", "republican", "bluewave", "senate", "governor",
    "democracy", "talarico", "hinojosa", "keisha", "abortion",
    "bluestate", "texasblue", "trump", "voting",
)
HOLIDAY_KEYS = (
    "halloween", "hallowe", "saturween", "diademuerto", "diadelosmuerto",
    "christmas", "costume", "harryween", "escapehalloween",
)
LIVE_KEYS = ("livefest", "livemonetization", "livecanbeeasy", "mylivejourney", "asktiktok")
MUSIC_KEYS = ("djremix", "calvinharris")


def parse_count(raw: str) -> float:
    s = (raw or "").strip().replace(",", "")
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)([KMB])?", s, re.I)
    if not m:
        raise ValueError(f"unrecognized count: {raw!r}")
    n = float(m.group(1))
    suf = (m.group(2) or "").upper()
    return n * {"": 1.0, "K": 1e3, "M": 1e6, "B": 1e9}[suf]


def fmt_count(n: float) -> str:
    if n >= 1e9:
        v = n / 1e9
        return f"{v:.1f}B".replace(".0B", "B") if v >= 10 else f"{v:.1f}B"
    if n >= 1e6:
        v = n / 1e6
        return f"{v:.1f}M"
    if n >= 1e3:
        v = n / 1e3
        return f"{v:.1f}K"
    return str(int(round(n)))


def classify_hashtag(tag: str) -> str:
    t = tag.strip().lower()
    if not t.startswith("#"):
        t = "#" + t
    if t in OVERRIDES:
        return OVERRIDES[t]
    if any(k in t for k in POLITICAL_KEYS):
        return "美国中期选举/政治"
    if any(k in t for k in HOLIDAY_KEYS):
        return "节日季"
    if any(k in t for k in LIVE_KEYS):
        return "TikTok官方活动/直播/创作者激励"
    if any(k in t for k in MUSIC_KEYS) or t == "#dj":
        return "音乐/DJ"
    return "其他/非英语"


@dataclass
class HashRow:
    period: int
    rank: int
    hashtag: str
    posts_raw: str
    views_raw: str
    industry: str
    posts: float
    views: float
    vpp: float
    bucket: str
    region: str = "US"
    detail_id: str = ""
    prev_rank: Optional[int] = None

    @property
    def signal(self) -> str:
        return ""  # filled later at set level


@dataclass
class CCAnalysis:
    rows: list
    d7: list
    d30: list
    new_tags: set
    sustain_tags: set
    fade_tags: set
    bucket7: dict
    bucket30: dict
    totals7: dict
    totals30: dict
    rank_changes: dict = field(default_factory=dict)
    has_prev: bool = False


def load_cc_csv(path: str) -> list:
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            period = int(raw["period_days"])
            rank = int(raw["rank"])
            tag = raw["hashtag"].strip()
            posts = parse_count(raw["posts"])
            views = parse_count(raw["views"])
            out.append(HashRow(
                period=period,
                rank=rank,
                hashtag=tag if tag.startswith("#") else f"#{tag}",
                posts_raw=raw["posts"].strip(),
                views_raw=raw["views"].strip(),
                industry=raw.get("industry", "").strip(),
                posts=posts,
                views=views,
                vpp=(views / posts) if posts else 0.0,
                bucket=classify_hashtag(tag),
                region=(raw.get("region") or "US").strip() or "US",
                detail_id=(raw.get("detail_id") or "").strip(),
            ))
    return out


def _bucket_stats(rows: list) -> tuple:
    stats = {b: {"n": 0, "posts": 0.0, "views": 0.0} for b in BUCKET_ORDER}
    for r in rows:
        slot = stats.setdefault(r.bucket, {"n": 0, "posts": 0.0, "views": 0.0})
        slot["n"] += 1
        slot["posts"] += r.posts
        slot["views"] += r.views
    totals = {
        "n": len(rows),
        "posts": sum(r.posts for r in rows),
        "views": sum(r.views for r in rows),
    }
    return stats, totals


def analyze_cc(csv_path: str, prev_csv_path: Optional[str] = None) -> CCAnalysis:
    rows = load_cc_csv(csv_path)
    d7 = [r for r in rows if r.period == 7]
    d30 = [r for r in rows if r.period == 30]
    s7 = {r.hashtag.lower() for r in d7}
    s30 = {r.hashtag.lower() for r in d30}
    b7, t7 = _bucket_stats(d7)
    b30, t30 = _bucket_stats(d30)
    analysis = CCAnalysis(
        rows=rows, d7=d7, d30=d30,
        new_tags=s7 - s30,
        sustain_tags=s7 & s30,
        fade_tags=s30 - s7,
        bucket7=b7, bucket30=b30,
        totals7=t7, totals30=t30,
    )
    if prev_csv_path:
        try:
            prev = load_cc_csv(prev_csv_path)
        except FileNotFoundError:
            prev = []
        if prev:
            analysis.has_prev = True
            for period in (7, 30):
                prev_map = {r.hashtag.lower(): r.rank for r in prev if r.period == period}
                cur = [r for r in rows if r.period == period]
                for r in cur:
                    pr = prev_map.get(r.hashtag.lower())
                    r.prev_rank = pr
                    analysis.rank_changes[(period, r.hashtag.lower())] = None if pr is None else pr - r.rank
    return analysis


def signal_of(row: HashRow, analysis: CCAnalysis) -> str:
    key = row.hashtag.lower()
    if key in analysis.new_tags:
        return "新冒头"
    if key in analysis.sustain_tags:
        return "持续热"
    if key in analysis.fade_tags:
        return "退潮"
    return ""


def row_by_tag(rows: list, tag: str) -> Optional[HashRow]:
    t = tag.lower() if tag.startswith("#") else f"#{tag.lower()}"
    for r in rows:
        if r.hashtag.lower() == t:
            return r
    return None


def rows_for_tag(rows: list, tag: str) -> list:
    t = tag.lower() if str(tag).startswith("#") else f"#{str(tag).lower()}"
    return [r for r in rows if r.hashtag.lower() == t]


def flag_7v30_for_tag(rows: list, tag: str, region: str | None = None) -> str:
    subset = rows_for_tag(rows, tag)
    if region:
        subset = [r for r in subset if r.region == region]
    pers = {r.period for r in subset}
    if pers == {7}:
        return "NEW_7D"
    if pers == {30}:
        return "FADE_30D"
    if pers == {7, 30}:
        return "SUSTAIN"
    return ""


def presence_table(rows: list, tags: list[str]) -> list[list[str]]:
    """Rows: [tag, region, 7d text, 30d text, flag]."""
    out = []
    for raw in tags or []:
        tag = raw if str(raw).startswith("#") else f"#{raw}"
        subset = rows_for_tag(rows, tag)
        regions = sorted({r.region for r in subset}) or ["—"]
        if not subset:
            out.append([tag, "—", "未上榜", "未上榜", "—"])
            continue
        for region in regions:
            r7 = next((r for r in subset if r.region == region and r.period == 7), None)
            r30 = next((r for r in subset if r.region == region and r.period == 30), None)
            def cell(r):
                return f"第{r.rank} · {r.posts_raw} / {r.views_raw}" if r else "未上榜"
            out.append([tag, region, cell(r7), cell(r30), flag_7v30_for_tag(rows, tag, region)])
    return out
