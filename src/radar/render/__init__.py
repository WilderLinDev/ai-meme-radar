"""Render a meme pack into `daily-report.md`, `daily-report.docx` and charts."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..config import Layout, Settings
from ..pack import Pack
from ..raw import History
from ..raw.schemas import Gap
from ..registry import Registry
from .charts import cc_chart, heat_chart, setup_font
from .document import build_document
from .docx import to_docx
from .markdown import to_markdown


def render_all(pack: Pack, hist: History, layout: Layout, settings: Settings, out_dir: Path) -> list[Path]:
    warning = setup_font(layout.font)
    if warning:
        pack.gaps.append(Gap(source="图表字体", note=warning))
    registry = Registry.load(layout.registry)
    charts: dict[str, list[tuple[Path, str]]] = {}
    written: list[Path] = []
    for m in pack.memes:
        if m.judgment.verdict != "make":
            continue
        items = []
        p = heat_chart(out_dir / f"heat-{m.id}.png", m.facts.name, m.id, hist, pack.date, m.facts.top_remixes)
        if p:
            items.append((p, f"{m.facts.display} 热度。上：每日热度；下：高播二创样本发布日。"))
        meme = registry[m.id]
        for tag in meme.cc_hashtags:
            region = meme.primary_region or _busiest_region(hist, tag)
            if not region:
                continue
            p = cc_chart(out_dir / f"cc-{tag}-{region.lower()}.png", tag, region, hist, pack.date)
            if p:
                items.append((p, f"#{tag} Creative Center 人气指数，7 日与 30 日各自归一化到 0–100，不能横比。"))
        charts[m.id] = items
        written += [p for p, _ in items]

    doc = build_document(pack, charts)
    md = out_dir / "daily-report.md"
    md.write_text(to_markdown(doc, out_dir), encoding="utf-8")
    docx = to_docx(doc, out_dir / "daily-report.docx")
    pack.write(layout.pack(pack.date))  # gaps may have grown (font warning)
    return [md, docx, *written]


def _busiest_region(hist: History, tag: str) -> str | None:
    counts = Counter(p.region for pts in hist.cc_curves.values() for p in pts if p.hashtag == tag and p.period == 30)
    return counts.most_common(1)[0][0] if counts else None
