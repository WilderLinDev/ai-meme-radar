# -*- coding: utf-8 -*-
"""Chart generation for the daily AI-video-meme report."""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter
import numpy as np

NAVY = "#1B3A4B"
TEAL = "#2A9D8F"
CORAL = "#E76F51"
GOLD = "#E9C46A"
SAND = "#F4A261"
INK = "#1A1A1A"
MUTED = "#5C6B73"
BG = "#FFFFFF"
GRID = "#E6E8EA"
CREAM = "#F7F4EE"

BUCKET_COLORS = {
    "美国中期选举/政治": "#C0392B",
    "节日季": "#E67E22",
    "影视/IP/明星": "#8E44AD",
    "TikTok官方活动/直播/创作者激励": "#2980B9",
    "音乐/DJ": "#16A085",
    "情感/故事类": "#D35400",
    "梗/挑战/可二创格式": "#27AE60",
    "其他/非英语": "#7F8C8D",
}


def setup_font(font_path: str):
    path = Path(font_path) if font_path else None
    if path and path.is_file():
        font_manager.fontManager.addfont(str(path))
        prop = font_manager.FontProperties(fname=str(path))
        family = prop.get_name()
    else:
        prop = font_manager.FontProperties(family="DejaVu Sans")
        family = "DejaVu Sans"
        print(f"FONT missing ({font_path}); charts use {family}. Chinese labels may not render.")
    plt.rcParams.update({
        "font.family": family,
        "font.size": 12,
        "axes.unicode_minus": False,
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "axes.edgecolor": "#D0D5D8",
        "axes.labelcolor": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "text.color": INK,
        "axes.titleweight": "bold",
        "axes.titlesize": 16,
        "figure.dpi": 140,
        "savefig.dpi": 140,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.25,
    })
    return prop


def _new(width=11.4, height=6.2):
    fig, ax = plt.subplots(figsize=(width, height))
    ax.set_axisbelow(True)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    return fig, ax


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return str(path)


def _fmt_num(n, _pos=None):
    if n >= 1e9:
        return f"{n/1e9:.1f}B"
    if n >= 1e6:
        return f"{n/1e6:.1f}M"
    if n >= 1e3:
        return f"{n/1e3:.0f}K"
    return f"{int(n)}"


def chart_ai_heat(chart_dir: Path, memes: list) -> str:
    """One panel per metric so mixed units are never drawn on the same axis."""
    color_map = {
        "X 7天发帖": CORAL,
        "ViralRemix/天": TEAL,
        "Turnly 创作者": GOLD,
        "原帖播放": SAND,
    }
    order = ["ViralRemix/天", "X 7天发帖", "Turnly 创作者", "原帖播放"]
    groups = []
    for met in order:
        chunk = [m for m in memes if m["metric"] == met]
        if chunk:
            groups.append((met, chunk))
    n = len(groups) or 1
    fig, axes = plt.subplots(n, 1, figsize=(11.4, 1.6 * n + 1.8), sharex=False)
    if n == 1:
        axes = [axes]
    fig.suptitle("今日 AI 梗核心热度（按口径分面，不在同一根轴上比较）", fontsize=16, fontweight="bold", y=0.98)
    for ax, (met, chunk) in zip(axes, groups):
        chunk = list(reversed(chunk))
        names = [f"{m['rank']}  {m['name']}" for m in chunk]
        values = [m["value"] for m in chunk]
        bars = ax.barh(names, values, color=color_map.get(met, NAVY), height=0.62, edgecolor="none")
        ax.xaxis.set_major_formatter(FuncFormatter(_fmt_num))
        ax.set_title(met, fontsize=12, loc="left", color=NAVY)
        for bar, val in zip(bars, values):
            ax.text(bar.get_width() * 1.01, bar.get_y() + bar.get_height() / 2,
                    _fmt_num(val), va="center", ha="left", fontsize=10, color=INK)
        ax.set_xlim(0, max(values) * 1.28)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="x", color=GRID, linewidth=0.7)
        ax.set_axisbelow(True)
        ax.grid(axis="y", visible=False)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.text(0.01, 0.01,
             "四个口径不可横比：ViralRemix 是日新增视频，X 是 7 天发帖，Turnly 是跟拍创作者数，原帖播放是单条视频的播放量。",
             fontsize=9, color=MUTED, ha="left")
    return _save(fig, chart_dir / "01_ai_meme_heat.png")


def chart_x_daily(chart_dir: Path, series: dict) -> str:
    """Line chart of available X daily endpoints. Does not invent missing days."""
    fig, ax = _new(11.4, 5.6)
    markers = {"Bicep Heart": "o", "Malfoid": "s"}
    colors = {"Bicep Heart": TEAL, "Malfoid": CORAL}
    for name, points in series.items():
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(xs, ys, color=colors.get(name, NAVY), marker=markers.get(name, "o"),
                linewidth=2.2, markersize=9, label=name, linestyle="--")
        for x, y in points:
            ax.annotate(f"{y:,}", (x, y), textcoords="offset points",
                        xytext=(0, 10), ha="center", fontsize=10, color=colors.get(name, NAVY))
    ax.set_title("Bicep Heart 与 Malfoid 的 X 每日发帖量（仅有两端读数）")
    ax.set_ylabel("当日 X 发帖数【已核实】")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda n, _p: f"{n:,.0f}"))
    ax.legend(frameon=False, loc="upper right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.grid(axis="x", visible=False)
    fig.text(0.01, -0.04,
             "本日报告只给出 11/4 与 11/9 两个端点，图中虚线/连线不代表中间各日的真实走势，故不用光滑插值。",
             fontsize=9, color=MUTED)
    return _save(fig, chart_dir / "02_x_daily_bicep_malfoid.png")


def chart_opportunity_matrix(chart_dir: Path, items: list) -> str:
    """Qualitative heat vs saturation scatter."""
    fig, ax = _new(11.4, 7.0)
    ax.axhspan(0, 4, xmin=0.5, xmax=1, color="#D5F5E3", alpha=0.55, zorder=0)
    ax.axhspan(4, 10, xmin=0.5, xmax=1, color="#FDEBD0", alpha=0.45, zorder=0)
    ax.axhspan(0, 10, xmin=0, xmax=0.5, color="#F4F6F7", alpha=0.4, zorder=0)
    ax.axvline(5, color="#D0D5D8", linewidth=1)
    ax.axhline(5, color="#D0D5D8", linewidth=1)
    ax.text(8.35, 0.55, "优先做：高热 + 模板未饱和", fontsize=9, color="#1E8449", ha="center")
    ax.text(8.35, 9.55, "谨慎：高热但竞争高", fontsize=9, color="#B9770E", ha="center")
    ax.text(1.85, 0.55, "观察：早期 / 热度仍低", fontsize=9, color=MUTED, ha="center")
    ax.text(3.55, 9.55, "避开：饱和或不是 AI 视频", fontsize=9, color=MUTED, ha="center")
    color_for = {
        "建议做": TEAL,
        "峰值可做": GOLD,
        "窗口将尽": SAND,
        "饱和": CORAL,
        "非AI视频": "#7F8C8D",
        "早期信号": NAVY,
    }
    for it in items:
        ax.scatter(it["heat"], it["sat"], s=220, color=color_for.get(it["tag"], NAVY),
                   zorder=3, edgecolors="white", linewidths=1.2)
        ax.annotate(it["name"], (it["heat"], it["sat"]),
                    textcoords="offset points", xytext=(8, 6), fontsize=10, color=INK)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.set_xlabel("热度（定性，综合 ViralRemix / X / 原帖，不是统一量纲）")
    ax.set_ylabel("竞争 / 模板饱和度（定性，CapCut 用量与跟拍拥挤程度）")
    ax.set_title("AI 梗机会矩阵（定性判断，不是精确坐标）")
    handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=c, markersize=10, label=lab)
        for lab, c in color_for.items()
        if any(it["tag"] == lab for it in items)
    ]
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.text(0.01, -0.03,
             "坐标来自今日报告里的判断（跟拍建议、CapCut 是否已做开、阶段是上升还是回落），不是模型打分。",
             fontsize=9, color=MUTED)
    return _save(fig, chart_dir / "03_opportunity_matrix.png")


def chart_bucket_share(chart_dir: Path, analysis) -> str:
    from .cc_lib import BUCKET_ORDER, fmt_count
    fig, axes = plt.subplots(2, 2, figsize=(11.4, 8.8))
    fig.suptitle("Creative Center 话题桶占比（美国 · News & Entertainment）", fontsize=16, fontweight="bold", y=0.98)
    specs = [
        (axes[0, 0], analysis.bucket7, analysis.totals7, "views", "近 7 日 · 按播放量"),
        (axes[0, 1], analysis.bucket7, analysis.totals7, "posts", "近 7 日 · 按帖子数"),
        (axes[1, 0], analysis.bucket30, analysis.totals30, "views", "近 30 日 · 按播放量"),
        (axes[1, 1], analysis.bucket30, analysis.totals30, "posts", "近 30 日 · 按帖子数"),
    ]
    for ax, bucket, totals, key, title in specs:
        labels, vals, colors = [], [], []
        for b in BUCKET_ORDER:
            v = bucket.get(b, {}).get(key, 0)
            if v <= 0:
                continue
            labels.append(b.replace("TikTok官方活动/直播/创作者激励", "官方/直播激励"))
            vals.append(v)
            colors.append(BUCKET_COLORS[b])
        y = np.arange(len(labels))
        ax.barh(y, vals, color=colors, height=0.7)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.set_title(title, fontsize=12)
        tot = totals[key] or 1
        ax.xaxis.set_major_formatter(FuncFormatter(_fmt_num))
        for i, v in enumerate(vals):
            ax.text(v * 1.01, i, f"{fmt_count(v)}  {100*v/tot:.1f}%", va="center", fontsize=8)
        ax.set_xlim(0, max(vals) * 1.38 if vals else 1)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="x", color=GRID, linewidth=0.7)
        ax.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.text(0.01, 0.01, "同一话题只归入一个主桶。政治桶在 7 日播放里占七成以上，节日季在 30 日被万圣节撑大。",
             fontsize=9, color=MUTED)
    return _save(fig, chart_dir / "04_cc_bucket_share.png")


def chart_top20(chart_dir: Path, rows: list, period: int, fname: str, title: str) -> str:
    data = sorted([r for r in rows if r.period == period], key=lambda r: r.rank)[:20]
    data = list(reversed(data))
    fig, ax = _new(11.4, 7.6)
    colors = [BUCKET_COLORS.get(r.bucket, "#7F8C8D") for r in data]
    ys = np.arange(len(data))
    ax.barh(ys, [r.views for r in data], color=colors, height=0.72)
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{r.rank:>2}  {r.hashtag}" for r in data], fontsize=10)
    ax.xaxis.set_major_formatter(FuncFormatter(_fmt_num))
    ax.set_xlabel("播放量")
    ax.set_title(title)
    for i, r in enumerate(data):
        ax.text(r.views * 1.01, i, f"{r.views_raw}  ·  {r.posts_raw}帖", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, max(r.views for r in data) * 1.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    used = []
    for r in data:
        if r.bucket not in used:
            used.append(r.bucket)
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=BUCKET_COLORS[b],
                      label=b.replace("TikTok官方活动/直播/创作者激励", "官方/直播激励"))
        for b in used
    ]
    ax.legend(handles=handles, loc="lower right", frameon=False, fontsize=8)
    return _save(fig, chart_dir / fname)


def chart_scatter(chart_dir: Path, rows: list, highlight: list, title: str, fname: str,
                  label_tags=None) -> str:
    fig, ax = _new(11.4, 7.2)
    hl = {h.lower() for h in highlight}
    label_set = {h.lower() for h in (label_tags or highlight)}
    others = [r for r in rows if r.hashtag.lower() not in hl]
    starred = [r for r in rows if r.hashtag.lower() in hl]
    ax.scatter([r.posts for r in others], [r.views for r in others],
               s=36, color="#B0B7BC", alpha=0.75, label="其他话题", zorder=2)
    if starred:
        ax.scatter([r.posts for r in starred], [r.views for r in starred],
                   s=90, color=CORAL, zorder=3, label="需关注 / 建议相关", edgecolors="white")
        # label each hashtag at most once (prefer the 7-day point)
        seen = set()
        labeled = sorted(starred, key=lambda r: (r.period != 7, r.rank))
        for r in labeled:
            key = r.hashtag.lower()
            if key in seen or key not in label_set:
                continue
            seen.add(key)
            ax.annotate(r.hashtag, (r.posts, r.views), textcoords="offset points",
                        xytext=(7, 6), fontsize=8, color=NAVY)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("帖子数（对数）")
    ax.set_ylabel("播放量（对数）")
    ax.set_title(title)
    ax.legend(frameon=False, loc="upper left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.text(0.01, -0.03,
             "越靠右上越热闹；同一帖子数下播放更高 = 更偏头部内容驱动。左下低播放/中等帖量通常更像大众参与。",
             fontsize=9, color=MUTED)
    return _save(fig, chart_dir / fname)


def chart_signals(chart_dir: Path, analysis) -> str:
    fig, ax = _new(11.4, 5.0)
    labels = ["新冒头\n（只在 7 日榜）", "持续热\n（两份榜都有）", "退潮\n（只在 30 日榜）"]
    vals = [len(analysis.new_tags), len(analysis.sustain_tags), len(analysis.fade_tags)]
    colors = [TEAL, GOLD, CORAL]
    bars = ax.bar(labels, vals, color=colors, width=0.55)
    ax.set_title("话题生命周期（由 7 日榜与 30 日榜差集推出，不是页面上的排名升降）")
    ax.set_ylabel("话题个数")
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 1.2, str(v), ha="center", fontsize=16, fontweight="bold")
    ax.set_ylim(0, max(vals) * 1.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.grid(axis="x", visible=False)
    fig.text(0.01, -0.04,
             "今日是接入 Creative Center 的第 1 天，页面本身不显示排名升降；该分组用两份榜的交集/差集近似生命周期。明天起会用昨日 CSV 计算名次变化。",
             fontsize=9, color=MUTED)
    return _save(fig, chart_dir / "08_cc_lifecycle.png")



def chart_share_rate_bar(chart_dir: Path, points: list, fname="09_share_rate.png") -> str:
    """Horizontal bar of median TikTok remix share rate, annotated with n."""
    pts = sorted(points, key=lambda s: s.median_share or 0)
    fig, ax = _new(11.4, max(5.2, 0.55 * len(pts) + 1.8))
    names = []
    for s in pts:
        nick = getattr(s, "nick", None) or s.meme
        plat = getattr(s, "platform", "")
        names.append(f"{nick} · {plat}" if plat and plat not in str(nick) else nick)
    vals = [100 * (s.median_share or 0) for s in pts]
    ns = [s.n for s in pts]
    plat_colors = {"TikTok": TEAL, "X": CORAL, "YouTube": GOLD, "Instagram": SAND}
    colors = []
    for s in pts:
        plat = getattr(s, "platform", "") or ""
        if plat in plat_colors:
            colors.append(plat_colors[plat])
        else:
            r = s.median_share or 0
            colors.append(TEAL if r >= 0.02 else GOLD if r >= 0.006 else CORAL)
    bars = ax.barh(names, vals, color=colors, height=0.62)
    ax.set_xlabel("二创中位分享率（分享 / 播放，%）")
    ax.set_title("各梗高播二创的分享率（按梗；颜色区分平台）")
    xmax = max(vals) * 1.28 if vals else 1
    ax.set_xlim(0, xmax)
    for bar, s, v, n in zip(bars, pts, vals, ns):
        w = s.weighted_share or 0
        ax.text(v + xmax * 0.015, bar.get_y() + bar.get_height() / 2,
                f"{v:.2f}%   n={n}   加权 {100*w:.2f}%",
                va="center", fontsize=9, color=INK)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    fig.text(0.01, -0.04,
             "样本为各梗播放最高的二创（约 5–10 条）。分享率高 = 格式更值得做。X 转发率不画在这张图里，不能和 TikTok 分享横比。",
             fontsize=9, color=MUTED)
    return _save(fig, chart_dir / fname)


def chart_heat_vs_share(chart_dir: Path, points: list, fname="10_heat_vs_share.png") -> str:
    """Scatter: remix-sample median views (log) vs median share rate."""
    fig, ax = _new(11.4, 7.0)
    ax.grid(True, color=GRID, linewidth=0.8)
    stage_color = {
        "上升": TEAL,
        "峰值": GOLD,
        "回落": CORAL,
        "早期": "#5B8FA8",
    }
    xs, ys = [], []
    for s in points:
        if not s.median_views or s.median_share is None:
            continue
        x, y = s.median_views, 100 * s.median_share
        xs.append(x); ys.append(y)
        stage = getattr(s, "stage", "") or ""
        plat = getattr(s, "platform", "") or ""
        plat_colors = {"TikTok": TEAL, "X": CORAL, "YouTube": GOLD, "Instagram": SAND}
        color = plat_colors.get(plat) or stage_color.get(stage, NAVY)
        marker = {"TikTok": "o", "X": "D", "YouTube": "s", "Instagram": "^"}.get(plat, "o")
        ax.scatter([x], [y], s=80 + 8 * s.n, color=color, zorder=3,
                   edgecolors="white", linewidths=0.8, marker=marker)
        nick = getattr(s, "nick", None) or s.meme
        offsets = {
            "切鱼梗": (10, -16),
            "Flamingo": (10, 10),
            "Can I Ride": (8, -16),
            "Ba Ba Ba": (8, 10),
            "Then I Walk In": (8, 10),
            "Shoulder Carry": (8, 6),
            "Cat Ultra Bee": (8, 8),
            "宠物摇头": (8, 8),
            "Bicep Heart": (8, 6),
        }
        ox, oy = offsets.get(nick, (8, 6))
        ax.annotate(f"{nick}\nn={s.n}", (x, y), textcoords="offset points",
                    xytext=(ox, oy), fontsize=8, color=NAVY)
    ax.set_xscale("log")
    ax.set_xlabel("样本中位播放量（对数，同口径二创样本）")
    ax.set_ylabel("中位分享率（%）")
    ax.set_title("机会矩阵：二创体量 vs 分享率（按梗；颜色/形状区分平台）")
    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=c,
                           markersize=9, label=lab)
               for lab, c in stage_color.items()]
    ax.legend(handles=handles, frameon=False, loc="upper left", fontsize=9, title="阶段")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if ys:
        ax.axhline(1.0, color="#D0D5D8", linestyle="--", linewidth=0.8)
    fig.text(0.01, -0.04,
             "右上：又有体量又有人转发，最值得做。左上：分享高但样本体量小（可能是新品或小众）。右下：很多人看、较少转发（舞类常见）。虚线 = 1% 分享率。",
             fontsize=9, color=MUTED)
    return _save(fig, chart_dir / fname)



def chart_meme_heat_panel(chart_dir: Path, meme_heat, fname: str) -> str:
    """Two-row panel: 7-day sources on top, longer remix-sample window below.

    Partial / same-day points are drawn as open markers and not connected if
    they sit on the edge. Missing dates stay as gaps.
    """
    from datetime import datetime, timedelta
    fig, axes = plt.subplots(2, 1, figsize=(11.4, 7.4), sharex=False)
    fig.subplots_adjust(hspace=0.38)
    title = getattr(meme_heat, "meme", "")
    fig.suptitle(f"{title} 热度曲线", fontsize=16, fontweight="bold", color=NAVY, y=0.98)

    def parse(d):
        return datetime.strptime(d, "%Y-%m-%d")

    # --- top: last ~11 days of X + ViralRemix ---
    ax = axes[0]
    ax.set_axisbelow(True)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax2 = None
    drawn = False
    xpts = meme_heat.points("x_posts")
    vpts = meme_heat.points("viralremix_new_videos")
    if xpts:
        xc = [p for p in xpts if p.complete]
        xp = [p for p in xpts if not p.complete]
        if xc:
            ax.plot([parse(p.date) for p in xc], [p.value for p in xc],
                    color=CORAL, marker="o", linewidth=2, markersize=6,
                    label="X 每日发帖（完整 UTC 日）")
            drawn = True
        if xp:
            ax.scatter([parse(p.date) for p in xp], [p.value for p in xp],
                       facecolors="none", edgecolors=CORAL, s=50, linewidths=1.4,
                       label="X 未满日（不参与峰值判断）", zorder=4)
            drawn = True
        ax.set_ylabel("X 发帖量", color=CORAL)
        ax.tick_params(axis="y", labelcolor=CORAL)
    if vpts:
        target = ax if not xpts else ax.twinx()
        if xpts:
            ax2 = target
        vc = [p for p in vpts if p.complete]
        vp = [p for p in vpts if not p.complete]
        if vc:
            target.plot([parse(p.date) for p in vc], [p.value for p in vc],
                        color=TEAL, marker="s", linewidth=2, markersize=6,
                        label="ViralRemix 每日新视频")
            drawn = True
        if vp:
            target.scatter([parse(p.date) for p in vp], [p.value for p in vp],
                           facecolors="none", edgecolors=TEAL, s=50, linewidths=1.4,
                           label="ViralRemix 当日页快照", zorder=4)
            drawn = True
        target.set_ylabel("ViralRemix 新视频 / 天", color=TEAL)
        target.tick_params(axis="y", labelcolor=TEAL)
        target.yaxis.set_major_formatter(FuncFormatter(_fmt_num))
    ax.yaxis.set_major_formatter(FuncFormatter(_fmt_num))
    ax.set_title("近 7–11 日（缺口不连线、不补点）")
    # legends combined
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ([], [])
    if ax2 is not None:
        h2, l2 = ax2.get_legend_handles_labels()
    if h1 or h2:
        ax.legend(h1 + h2, l1 + l2, frameon=False, fontsize=8, loc="upper left")
    if not drawn:
        ax.text(0.5, 0.5, "近 7 日没有可用的 X / ViralRemix 曲线", ha="center", va="center",
                transform=ax.transAxes, color=MUTED)
    ax.spines["top"].set_visible(False)

    # --- bottom: remix sample over whatever date span exists ---
    ax = axes[1]
    ax.set_axisbelow(True)
    ax.grid(True, color=GRID, linewidth=0.8)
    rposts = meme_heat.points("remix_sample_posts", complete_only=True)
    rviews = meme_heat.points("remix_sample_views", complete_only=True)
    if rposts:
        ax.bar([parse(p.date) for p in rposts], [p.value for p in rposts],
               color="#8ECAE6", width=0.8, label="样本二创发布条数")
        ax.set_ylabel("发布条数")
    if rviews:
        axv = ax.twinx()
        xs = [parse(p.date) for p in rviews]
        ys = []
        acc = 0
        for p in rviews:
            acc += p.value
            ys.append(acc)
        axv.plot(xs, ys, color=NAVY, marker=".", linewidth=1.6, label="样本播放累计（按发布日）")
        axv.set_ylabel("累计播放")
        axv.yaxis.set_major_formatter(FuncFormatter(_fmt_num))
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = axv.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, frameon=False, fontsize=8, loc="upper left")
    elif rposts:
        ax.legend(frameon=False, fontsize=8, loc="upper left")
    else:
        ax.text(0.5, 0.5, "没有二创样本的发布日期可画", ha="center", va="center",
                transform=ax.transAxes, color=MUTED)
    ax.set_title("更长窗口：高播二创样本的发布日（不是全站日产量）")
    ax.set_xlabel("日期")
    ax.spines["top"].set_visible(False)
    fig.text(0.01, 0.01,
             "空心点 = 未满日或当日快照，不参与回落百分比。ViralRemix 2026-11-03 日榜 404，保持缺口。Google Trends 此次被 429 挡住。",
             fontsize=8, color=MUTED)
    return _save(fig, Path(chart_dir) / fname)



def chart_cc_hashtag_trend(chart_dir: Path, trend, fname: str) -> str:
    """Dual-panel 30-day + 7-day Creative Center popularity index (0-100)."""
    from datetime import datetime, timedelta
    from matplotlib.dates import DateFormatter

    def parse(d):
        return datetime.strptime(d, "%Y-%m-%d")

    def draw(ax, pts, color, title):
        ax.set_axisbelow(True)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_title(title)
        ax.set_ylabel("人气指数")
        ax.set_ylim(-4, 108)
        ax.spines["top"].set_visible(False)
        if not pts:
            ax.text(0.5, 0.5, "没有这一窗口的读数", ha="center", va="center",
                    transform=ax.transAxes, color=MUTED)
            return
        xs = [parse(p.date) for p in pts]
        ys = [p.value for p in pts]
        run_x, run_y = [], []
        zeros_x, zeros_y = [], []
        prev = None
        first_line = True
        for p, x, y in zip(pts, xs, ys):
            d = parse(p.date)
            if y == 0:
                if run_x:
                    ax.plot(run_x, run_y, color=color, marker="o", linewidth=2,
                            markersize=5, label="人气指数" if first_line else None)
                    first_line = False
                    run_x, run_y = [], []
                zeros_x.append(x)
                zeros_y.append(y)
                prev = d
                continue
            if prev is not None and (d - prev).days > 1 and run_x:
                ax.plot(run_x, run_y, color=color, marker="o", linewidth=2,
                        markersize=5, label="人气指数" if first_line else None)
                first_line = False
                run_x, run_y = [], []
            run_x.append(x)
            run_y.append(y)
            prev = d
        if run_x:
            ax.plot(run_x, run_y, color=color, marker="o", linewidth=2,
                    markersize=5, label="人气指数" if first_line else None)
        if zeros_x:
            ax.scatter(zeros_x, zeros_y, facecolors="none", edgecolors=color,
                       s=55, linewidths=1.4, label="读数为 0（按缺口处理，不连线）", zorder=4)
        usable = [p for p in pts if p.value > 0]
        if usable:
            peak = max(usable, key=lambda p: p.value)
            last = pts[-1]
            ax.annotate(f"峰值 {peak.value:g}\n{peak.date[5:]}",
                        xy=(parse(peak.date), peak.value),
                        xytext=(8, -18), textcoords="offset points",
                        fontsize=8, color=NAVY)
            if last.date != peak.date:
                ax.annotate(f"{last.value:g}",
                            xy=(parse(last.date), last.value),
                            xytext=(6, 8), textcoords="offset points",
                            fontsize=8, color=color)
        ax.xaxis.set_major_formatter(DateFormatter("%m-%d"))
        h, l = ax.get_legend_handles_labels()
        if h:
            ax.legend(h, l, frameon=False, fontsize=8, loc="upper left")

    fig, axes = plt.subplots(2, 1, figsize=(11.4, 7.2), sharex=False)
    fig.subplots_adjust(hspace=0.36)
    tag = trend.hashtag
    t30 = trend.totals.get(30) or {}
    t7 = trend.totals.get(7) or {}
    extra30 = ""
    if t30.get("posts") or t30.get("views"):
        extra30 = f"；窗口合计 {t30.get('posts') or '?'} 帖 / {t30.get('views') or '?'} 播放"
    extra7 = ""
    if t7.get("posts") or t7.get("views"):
        extra7 = f"；窗口合计 {t7.get('posts') or '?'} 帖 / {t7.get('views') or '?'} 播放"
    r30 = ""
    r7 = ""
    regions = getattr(trend, "regions", {}) or {}
    if regions.get(30):
        r30 = f"，{regions[30]}"
    if regions.get(7):
        r7 = f"，{regions[7]}"
    fig.suptitle(f"#{tag} Creative Center 人气曲线",
                 fontsize=16, fontweight="bold", color=NAVY, y=0.98)
    draw(axes[0], trend.points(30), TEAL,
         f"近 30 日人气指数（0–100，窗口内相对值{r30}{extra30}）")
    draw(axes[1], trend.points(7), CORAL,
         f"近 7 日人气指数（0–100，另一套相对值，不能与上图横比{r7}{extra7}）")
    axes[1].set_xlabel("日期")
    fig.text(0.01, 0.01,
             "来源：TikTok Creative Center 话题详情页 popularity index【第三方读数】。"
             "读数为 0 的日期画空心点、不把前后连起来。不插值、不补点。",
             fontsize=8, color=MUTED)
    return _save(fig, Path(chart_dir) / fname)


def make_all_charts(chart_dir: Path, font_path: str, analysis, extra: dict) -> dict:
    setup_font(font_path)
    chart_dir = Path(chart_dir)
    paths = {}
    if extra.get("ai_heat"):
        paths["ai_heat"] = chart_ai_heat(chart_dir, extra["ai_heat"])
    if extra.get("x_daily"):
        paths["x_daily"] = chart_x_daily(chart_dir, extra["x_daily"])
    remix_pts = extra.get("remix_points") or []
    if remix_pts:
        paths["share_bar"] = chart_share_rate_bar(chart_dir, remix_pts)
        paths["heat_share"] = chart_heat_vs_share(chart_dir, remix_pts)
    elif extra.get("matrix"):
        paths["matrix"] = chart_opportunity_matrix(chart_dir, extra["matrix"])
    paths["buckets"] = chart_bucket_share(chart_dir, analysis)
    if extra.get("include_cc_extras"):
        paths["top20_7"] = chart_top20(
            chart_dir, analysis.d7, 7, "05_cc_top20_7d.png",
            "近 7 日 Top 20（按 Creative Center 排名，柱长=播放量）")
        paths["top20_30"] = chart_top20(
            chart_dir, analysis.d30, 30, "06_cc_top20_30d.png",
            "近 30 日 Top 20（按 Creative Center 排名，柱长=播放量）")
        paths["scatter"] = chart_scatter(
            chart_dir, analysis.d7 + analysis.d30, extra["highlight_tags"],
            "帖子数 vs 播放量（对数，7 日与 30 日合并描点；同一话题可能出现两次）",
            "07_cc_scatter.png",
            label_tags=extra.get("label_tags") or extra["highlight_tags"])
    paths["lifecycle"] = chart_signals(chart_dir, analysis)
    heat_map = extra.get("heat") or {}
    meme_heat_charts = {}
    for name, mh in heat_map.items():
        slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")
        fname = f"heat_{slug}.png"
        meme_heat_charts[name] = chart_meme_heat_panel(chart_dir, mh, fname)
    if meme_heat_charts:
        paths["meme_heats"] = meme_heat_charts
    cc_trends = extra.get("cc_trends") or {}
    cc_charts = {}
    for tag, tr in cc_trends.items():
        if not getattr(tr, "has_series", lambda: False)():
            continue
        slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in tag).strip("_")
        cc_charts[tag] = chart_cc_hashtag_trend(chart_dir, tr, f"cc_trend_{slug}.png")
    if cc_charts:
        paths["cc_trends"] = cc_charts
        if "lastchristmas" in cc_charts:
            paths["cc_lastchristmas"] = cc_charts["lastchristmas"]
    return paths
