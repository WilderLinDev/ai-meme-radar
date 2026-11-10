"""Preflight: what is present, what to ask for, what is skipped."""
from __future__ import annotations

import json

from .config import CC_INDUSTRY, CC_PERIODS, CC_REGIONS, PLATFORMS, Layout, Settings, config_dir
from .csvio import DataError, read_dicts
from .registry import Registry

WATCHLIST_REQUIRED = ("platform", "handle", "profile_url", "type", "selected")


def preflight(layout: Layout, settings: Settings) -> tuple[list[str], list[str], list[str]]:
    present, ask, skipped = [], [], []

    rows = read_dicts(layout.watchlist)
    if rows and all(c in rows[0] for c in WATCHLIST_REQUIRED):
        selected = sum(1 for r in rows if r["selected"] == "yes")
        present.append(f"config/watchlist.csv（{selected} 个已选账号）")
    else:
        ask.append("config/watchlist.csv 缺失或缺列 " + ", ".join(WATCHLIST_REQUIRED) + "。没有它就跳过监控号抓取。")

    try:
        reg = Registry.load(layout.registry)
        present.append(f"data/memes.csv（{len(reg.memes)} 个已登记的梗）")
    except DataError as e:
        ask.append("data/memes.csv 有错误，先修好：" + "；".join(e.problems[:5]))

    if layout.font.is_file():
        present.append(f"中文字体 {layout.font}")
    else:
        skipped.append(f"字体 {layout.font} 不在，图表会改用系统里能找到的中文字体。不用问。")

    lark = settings.lark
    if not lark.enabled:
        skipped.append("Lark 同步关闭（lark.enabled = false）。不导入 Wiki、不追加 Base。不用问。")
    else:
        schema = json.loads(layout.lark_schema.read_text(encoding="utf-8"))
        missing = [k for k in ("base_app_token", "wiki_parent_url") if not getattr(lark, k)]
        missing += [f"tables.{t['key']}" for t in schema["tables"] if not lark.tables.get(t["key"])]
        if missing:
            ask.append("Lark 已打开，但 settings.toml 缺 " + ", ".join("lark." + m for m in missing)
                       + "。不给就只跳过 Lark，日报照常写。")
        else:
            present.append("Lark base token、Wiki 父节点、全部表 id")

    ask.append("运行时才知道：X API（get_posts_counts_recent）没授权就问一次；不给就跳过 X 热度并记缺口。")
    ask.append("运行时才知道：浏览器里 TikTok Creative Center 没登录就问一次；不给就跳过 8 区榜单并记缺口。")
    skipped.append("Instagram 登录可选。没登录就跳过 Instagram 监控号并记缺口，不要替用户登录。")
    return present, ask, skipped


def report(layout: Layout, settings: Settings) -> str:
    present, ask, skipped = preflight(layout, settings)
    lines = [
        "范围固定，不要问用户：",
        f"  平台 {' → '.join(PLATFORMS)}；辅证 X、YouTube Shorts、Reddit；不看抖音。",
        f"  Creative Center {', '.join(CC_REGIONS)} × {'/'.join(map(str, CC_PERIODS))} 日，行业 {CC_INDUSTRY}；NL 不提供，跳过并说明。",
        "  监控号：config/watchlist.csv 全部已选行。日报语言：中文。",
        f"  本地设置：{settings.source or config_dir() / 'settings.toml'}"
        + ("" if settings.source else "（不存在，按默认值运行）"),
        "",
    ]
    for title, rows in (("Present", present), ("Ask", ask), ("Skipped", skipped)):
        lines.append(title)
        lines += [f"  - {r}" for r in rows] or ["  (none)"]
    return "\n".join(lines)
