"""Peak status from a daily series. Gaps stay gaps; nothing is interpolated."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

NEAR_PEAK_DROP = 0.15  # within 15% of the peak counts as near the peak (docs/scoring.md)

Status = Literal["rising", "peak", "near_peak", "declining", "unknown"]
STATUS_ZH = {"rising": "上升中", "peak": "峰值", "near_peak": "接近峰值", "declining": "回落", "unknown": "数据不足"}


@dataclass(frozen=True)
class Point:
    date: date
    value: float


@dataclass(frozen=True)
class Lifecycle:
    status: Status
    points: int
    peak: Point | None = None
    last: Point | None = None
    drop: float | None = None  # fraction below the peak at the last point

    @property
    def label_zh(self) -> str:
        if self.status == "unknown":
            return f"数据不足（可用点 {self.points} 个）"
        assert self.peak and self.last
        peak = f"峰值 {self.peak.date:%m-%d} 的 {self.peak.value:g}"
        if self.status in ("rising", "peak"):
            return f"{STATUS_ZH[self.status]}（{peak}）"
        return f"{STATUS_ZH[self.status]} {self.drop * 100:.0f}%（{peak} → {self.last.date:%m-%d} 的 {self.last.value:g}）"


def classify(points: list[Point]) -> Lifecycle:
    """`points` must already be complete, on or before the report date, and exclude gaps."""
    pts = sorted(points, key=lambda p: p.date)
    if len(pts) < 2:
        return Lifecycle("unknown", len(pts))
    peak = max(pts, key=lambda p: (p.value, p.date))
    last = pts[-1]
    if last.date == peak.date:
        status: Status = "rising" if last.value > pts[-2].value else "peak"
        return Lifecycle(status, len(pts), peak, last, 0.0)
    drop = (peak.value - last.value) / peak.value if peak.value else 0.0
    status = "near_peak" if drop <= NEAR_PEAK_DROP else "declining"
    return Lifecycle(status, len(pts), peak, last, drop)
