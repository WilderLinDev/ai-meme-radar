"""The two charts the report uses: a meme's heat panel and a hashtag's CC curves.

Partial points are hollow and never joined. Gaps stay gaps. Nothing is interpolated.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.dates import DateFormatter  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from ..raw import History  # noqa: E402
from ..raw.schemas import Remix  # noqa: E402

NAVY, TEAL, CORAL, MUTED, GRID = "#1B3A4B", "#2A9D8F", "#E76F51", "#5C6B73", "#E6E8EA"
CJK_FALLBACKS = ("Noto Sans CJK SC", "Noto Sans SC", "PingFang SC", "Heiti SC", "Hiragino Sans GB",
                 "Microsoft YaHei", "Arial Unicode MS")
METRIC_STYLE = {
    "x_posts": ("X 每日发帖", CORAL, "o"),
    "viralremix_new_videos": ("ViralRemix 每日新视频", TEAL, "s"),
}


def setup_font(font_path: Path) -> str | None:
    """Use the configured font, else any installed CJK font. Returns a warning or None."""
    family = None
    if font_path.is_file():
        font_manager.fontManager.addfont(str(font_path))
        family = font_manager.FontProperties(fname=str(font_path)).get_name()
    else:
        installed = {f.name for f in font_manager.fontManager.ttflist}
        family = next((f for f in CJK_FALLBACKS if f in installed), None)
    plt.rcParams.update({
        "font.family": family or "DejaVu Sans", "axes.unicode_minus": False, "font.size": 11,
        "axes.titleweight": "bold", "savefig.dpi": 140, "savefig.bbox": "tight",
    })
    if family is None:
        return f"没有找到中文字体（{font_path}），图里的中文可能显示为方块。"
    return None


def _num(n, _pos=None) -> str:
    for floor, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= floor:
            return f"{n / floor:.1f}{suf}"
    return f"{n:g}"


def _axis(ax, title: str) -> None:
    ax.set_title(title)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.xaxis.set_major_formatter(DateFormatter("%m-%d"))


def _runs(points: list[tuple[date, float]]) -> list[list[tuple[date, float]]]:
    """Split into runs of consecutive days so gaps are not bridged."""
    runs: list[list[tuple[date, float]]] = []
    for d, v in sorted(points):
        if runs and (d - runs[-1][-1][0]).days == 1:
            runs[-1].append((d, v))
        else:
            runs.append([(d, v)])
    return runs


def heat_chart(path: Path, title: str, meme_id: str, hist: History, day: date, remixes: list[Remix]) -> Path | None:
    metrics = [m for m in METRIC_STYLE if hist.series(meme_id, m)]
    dated = [r for r in remixes if r.posted_on]
    if not metrics and not dated:
        return None
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(11.4, 7.2))
    fig.subplots_adjust(hspace=0.4)
    fig.suptitle(f"{title} 热度", color=NAVY, fontsize=15, fontweight="bold")
    _axis(top, "每日热度（空心点为未满日，不参与峰值计算；缺口不连线）")
    axes = {}
    for i, metric in enumerate(metrics):
        label, color, marker = METRIC_STYLE[metric]
        ax = top if i == 0 else top.twinx()
        axes[metric] = ax
        pts = [p for p in hist.series(meme_id, metric) if p.date <= day]
        for run in _runs([(p.date, p.value) for p in pts if p.complete]):
            ax.plot([d for d, _ in run], [v for _, v in run], color=color, marker=marker, linewidth=2, label=label)
        partial = [p for p in pts if not p.complete]
        if partial:
            ax.scatter([p.date for p in partial], [p.value for p in partial], facecolors="none",
                       edgecolors=color, s=50, label=f"{label}（未满日）", zorder=4)
        ax.set_ylabel(label, color=color)
        ax.yaxis.set_major_formatter(FuncFormatter(_num))
    handles = [h for ax in axes.values() for h in ax.get_legend_handles_labels()[0]]
    labels = [l for ax in axes.values() for l in ax.get_legend_handles_labels()[1]]
    seen = {}
    for h, l in zip(handles, labels):
        seen.setdefault(l, h)
    if seen:
        top.legend(list(seen.values()), list(seen), frameon=False, fontsize=8, loc="upper left")
    else:
        top.text(0.5, 0.5, "没有 X / ViralRemix 日序列", ha="center", va="center", transform=top.transAxes, color=MUTED)

    _axis(bottom, "高播二创样本的发布日（不是全站日产量）")
    if dated:
        counts = Counter(r.posted_on for r in dated)
        bottom.bar(list(counts), list(counts.values()), color="#8ECAE6", width=0.8)
        bottom.set_ylabel("发布条数")
        bottom.yaxis.set_major_locator(MaxNLocator(integer=True))
    else:
        bottom.text(0.5, 0.5, "二创样本没有发布日期", ha="center", va="center", transform=bottom.transAxes, color=MUTED)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


def cc_chart(path: Path, hashtag: str, region: str, hist: History, day: date) -> Path | None:
    capture = next((c for c in hist.curve_captures(hashtag, region, 30) + hist.curve_captures(hashtag, region, 7)
                    if c <= day), None)
    if capture is None:
        return None
    fig, axes = plt.subplots(2, 1, figsize=(11.4, 7.0))
    fig.subplots_adjust(hspace=0.4)
    fig.suptitle(f"#{hashtag} Creative Center 人气指数（{region}，{capture} 抓取）", color=NAVY, fontsize=15, fontweight="bold")
    for ax, period, color in ((axes[0], 30, TEAL), (axes[1], 7, CORAL)):
        _axis(ax, f"近 {period} 日（0–100，窗口内相对值；两图不能横比）")
        ax.set_ylim(-4, 108)
        pts = [(p.date, p.value) for p in hist.curve(hashtag, region, period, capture)]
        real = [(d, v) for d, v in pts if v > 0]
        for run in _runs(real):
            ax.plot([d for d, _ in run], [v for _, v in run], color=color, marker="o", linewidth=2)
        zeros = [d for d, v in pts if v == 0]
        if zeros:
            ax.scatter(zeros, [0] * len(zeros), facecolors="none", edgecolors=color, s=50,
                       label="读数为 0（按缺口处理）", zorder=4)
            ax.legend(frameon=False, fontsize=8, loc="upper left")
        if not pts:
            ax.text(0.5, 0.5, "没有这一窗口的读数", ha="center", va="center", transform=ax.transAxes, color=MUTED)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path
