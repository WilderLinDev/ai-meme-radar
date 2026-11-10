"""Mechanical checks on judgments. The rubric itself is docs/scoring.md."""
from __future__ import annotations

from .judgments import PLACEHOLDER, Judgments, MemeJudgment, Scores, Verdict

MAKE_TOTAL = 65
MAKE_WINDOW = 10
WATCH_TOTAL = 45


def suggested_verdict(scores: Scores) -> Verdict:
    if scores.total >= MAKE_TOTAL and scores.window.score >= MAKE_WINDOW:
        return "make"
    if scores.total >= WATCH_TOTAL:
        return "watch"
    return "skip"


def is_override(j: MemeJudgment) -> bool:
    return j.verdict != suggested_verdict(j.scores)


def share_hint(median: float | None, enough: bool) -> str:
    if not enough or median is None:
        return "样本不足 → 6"
    for floor, band in ((0.03, "18–20"), (0.02, "15–17"), (0.01, "12–14"), (0.006, "8–11"), (0.003, "4–7")):
        if median >= floor:
            return f"中位 {median * 100:.2f}% → {band}"
    return f"中位 {median * 100:.2f}% → 0–3"


def trend_hint(status: str, drop: float | None) -> str:
    if status == "rising":
        return "上升中 → 16–20"
    if status == "near_peak":
        return "接近峰值 → 12–15"
    if status == "peak":
        return "峰值或走平 → 8–11"
    if status == "declining" and drop is not None:
        return f"回落 {drop * 100:.0f}% → " + ("4–7" if drop <= 0.40 else "0–3")
    return "没有可用曲线 → 8"


def heat_hint(viralremix_last: float | None, x_7d: float | None) -> str:
    bits = []
    if viralremix_last is not None:
        v = viralremix_last
        band = ("18–20" if v >= 40_000 else "16–17" if v >= 20_000 else "12–15" if v >= 5_000
                else "8–11" if v >= 1_000 else "4–7" if v >= 100 else "0–3")
        bits.append(f"ViralRemix 最近完整日 {v:g} → {band}")
    if x_7d is not None:
        bits.append(f"X 近 7 日完整日合计 {x_7d:g}" + (" → 18–20" if x_7d >= 100_000 else ""))
    return "；".join(bits) or "没有 ViralRemix / X 日序列，按其他证据给分"


def check(j: Judgments) -> list[str]:
    """Problems that must be fixed before a pack can be built."""
    problems = []
    seen: set[str] = set()
    for m in j.memes:
        where = f"judgments.json {m.meme_id}"
        if m.meme_id in seen:
            problems.append(f"{where}: judged twice")
        seen.add(m.meme_id)
        if is_override(m) and not m.override_reason.strip():
            problems.append(
                f"{where}: verdict {m.verdict} differs from suggested {suggested_verdict(m.scores)} "
                f"(total {m.scores.total}, window {m.scores.window.score}); fill override_reason")
        if not m.reason.strip() or PLACEHOLDER in m.reason:
            problems.append(f"{where}: reason is empty")
    for g in j.excluded_hashtags:
        if not g.reason.strip() or PLACEHOLDER in g.reason:
            problems.append(f"judgments.json excluded_hashtags {g.tags[:3]}…: reason is empty")
    return problems
