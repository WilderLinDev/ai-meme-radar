"""The daily steps: ingest, scaffold, build. Each one is a plain function."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import backtest, tracker
from .config import Layout, Settings
from .csvio import DataError
from .judgments import Judgments
from .pack import Pack, PackMeme, compute_facts, coverage_problems, day_gaps, finish_facts, scaffold
from .analysis import cc as cc_analysis
from .raw import RawDay, load_day, load_history
from .registry import Registry
from .scoring import check


def ingest(layout: Layout, day: date) -> tuple[RawDay, Registry]:
    registry = Registry.load(layout.registry)
    raw = load_day(layout, day, registry)
    return raw, registry


def candidates(raw: RawDay, registry: Registry, existing: Judgments | None) -> list:
    ids = raw.meme_ids()
    ids |= {registry.by_hashtag[r.hashtag] for r in raw.cc_top100 if r.hashtag in registry.by_hashtag}
    if existing:
        ids |= {m.meme_id for m in existing.memes}
    return [registry[i] for i in sorted(ids)]


def write_scaffold(layout: Layout, day: date) -> Path:
    raw, registry = ingest(layout, day)
    path = layout.judgments(day)
    existing = Judgments.load(path) if path.is_file() else None
    hist = load_history(layout, day)
    rows = tracker.load(layout.tracker)
    cands = candidates(raw, registry, existing)
    facts = {m.id: compute_facts(m, raw, hist, tracker.previous(rows, m.id, day)) for m in cands}
    linked = {t for t, mid in registry.by_hashtag.items() if mid in facts}
    excluded = existing.excluded_tags() if existing else set()
    left = cc_analysis.unaccounted(raw.cc_top100, linked, excluded)
    draft = scaffold(existing, day, cands, facts, left)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@dataclass
class BuildResult:
    pack: Pack
    outputs: list[Path]


def build(layout: Layout, settings: Settings, day: date, render: bool = True) -> BuildResult:
    raw, registry = ingest(layout, day)
    judgments = Judgments.load(layout.judgments(day))
    if judgments.date != day:
        raise DataError([f"judgments.json is dated {judgments.date}, expected {day}"])
    registry.require([m.meme_id for m in judgments.memes], "judgments.json")
    problems = check(judgments) + coverage_problems(judgments, registry.by_hashtag, raw)
    if problems:
        raise DataError(problems)

    hist = load_history(layout, day)
    rows = tracker.load(layout.tracker)
    memes = []
    for j in judgments.memes:
        meme = registry[j.meme_id]
        f = compute_facts(meme, raw, hist, tracker.previous(rows, meme.id, day))
        memes.append(PackMeme(judgment=j, facts=finish_facts(f, j, day)))

    rows = tracker.replace_day(layout.tracker, day, [_tracker_row(day, m) for m in memes])
    evals, summary = backtest.evaluate(rows, registry, hist, day)
    backtest.write(evals, summary, layout.backtest_json, layout.backtest_csv)
    for m in memes:
        m.facts.backtest_line = backtest.latest_line(evals, m.id, day)

    gaps, lists = day_gaps(raw)
    pack = Pack(date=day, memes=memes, excluded_hashtags=judgments.excluded_hashtags,
                notes=judgments.notes, gaps=gaps, cc_lists=lists, backtest=summary)
    out_dir = layout.report_dir(day)
    pack.write(layout.pack(day))
    outputs = [layout.pack(day), layout.tracker, layout.backtest_json]
    if render:
        from .render import render_all
        outputs += render_all(pack, hist, layout, settings, out_dir)
    return BuildResult(pack=pack, outputs=outputs)


def _tracker_row(day: date, m: PackMeme) -> dict:
    j, f = m.judgment, m.facts
    tiktok = f.tiktok_share
    return {
        "date": day.isoformat(), "meme_id": j.meme_id, "name": f.name, "part": j.part,
        "verdict": j.verdict, "suggested_verdict": f.suggested_verdict, "total": f.total,
        **{d: getattr(j.scores, d).score for d in ("heat", "trend", "share", "competition", "window")},
        "primary_metric": f.primary_metric,
        "primary_value": "" if f.primary_value is None else f"{f.primary_value:g}",
        "primary_date": f.primary_date.isoformat() if f.primary_date else "",
        "share_median": f"{tiktok.median:.5f}" if tiktok and tiktok.median is not None else "",
        "share_n": tiktok.n if tiktok else "",
        "ignite_date": j.ignite_date.isoformat() if j.ignite_date else "",
        "days_hot": "" if f.days_hot is None else f.days_hot,
        "peak_status": f.peak_status,
        "cc_regions": ",".join(sorted({c.region for c in f.cc})),
    }
