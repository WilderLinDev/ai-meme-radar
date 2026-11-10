#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_report.py
===============
Build the AI-video-meme daily report. The document has exactly three parts:

  一、总排名     ranking table (internal links to each meme)
  二、逐个梗详解  scored memes ordered by 综合评分 (观望/不做 included)
  三、早期信号    early-signal memes, same seven sub-blocks

Each meme section: 结论卡 → 是什么+链接 → 热度曲线 → 二创分享率
→ 竞争与模板 → 怎么做 → 风险.

Typical run for 2026-11-10
--------------------------
  python scripts/build_report.py \\
      --date 2026-11-10 \\
      --pack reports/2026-11/2026-11-10-meme-pack.json \\
      --md reports/2026-11/2026-11-10-daily-report.md \\
      --cc-csv reports/2026-11/2026-11-10-cc-top100.csv \\
      --remix-csv reports/2026-11/2026-11-10-remix-stats.csv \\
      --heat-json reports/2026-11/2026-11-10-heat.json \\
      --cc-trends-csv reports/2026-11/2026-11-10-cc-hashtag-trends.csv

  Word, charts and the markdown all land in reports/2026-11/ with the date
  prefix (2026-11-10-daily-report.docx, 2026-11-10-heat-<slug>.png).
  Lark Wiki import is not part of this script. Pass --sync-lark only to
  print that Base sync is allowed; batches are built by scripts/sync_lark.py.

Inputs
------
--pack PATH         Required JSON of per-meme fields: scores (热度/趋势/分享率/
                    竞争/窗口 + total), verdict, window, reason, ignite_date,
                    days_hot / days_hot_label, peak_status, what, origin,
                    originals/examples/trackers (with urls), howto (play,
                    user_input, tools, prompt, negative_prompt, bgm, caption,
                    hashtags), risks, competition, cc_hashtags, part
                    (main|early), source_tag, remix_key, heat_* notes.
                    Scores are written from real data in the pack; the builder
                    does not invent them. Rubric text lives in pack["rubric"].
--md PATH           Optional digest markdown (facts stay in the pack; the md
                    is accepted so a daily run can keep passing it).
--cc-csv PATH       Creative Center US N&E Top 100 export (7d + 30d). Used
                    inside a meme's 热度曲线 block when the pack lists
                    cc_hashtags, and to support CC-derived meme entries.
--cc-trends-csv PATH
                    Optional hashtag-detail popularity curves
                    (hashtag,period_days,date,value,...). Detail pages exist
                    only for hashtags currently in the Top 100. When a packed
                    meme lists a matching cc_hashtag and the CSV has daily
                    points, the builder draws a 7d+30d chart under 热度曲线.
                    New tags can be appended to the same CSV and picked up
                    on the next run — no pack edit required for the chart.
--remix-csv PATH    High-view remix samples (originals already excluded).
                    Fills the merged share-rate table and example links.
--heat-json PATH    Per-meme X / ViralRemix / remix-sample time series.
                    CSV alternative: --heat-csv.
--date YYYY-MM-DD   Report date (default: pack["report_date"]).
--out-docx PATH     Output Word file. Default: reports/YYYY-MM/YYYY-MM-DD-daily-report.docx.
--chart-dir PATH    PNG directory. Default: that same month folder (no charts/ subdirectory).
                    Filenames are YYYY-MM-DD-heat-<slug>.png and YYYY-MM-DD-cc-trend-<slug>.png.
--font PATH         CJK font. Default: assets/fonts/NotoSansSC-Regular.otf (not bundled).
--sync-lark         Note that Lark sync is enabled. This script still only writes files.
--no-lark           Force the Lark note off. Default is off.

CC-derived memes
----------------
A Creative Center hashtag becomes its own scored section when it is listed
in the pack with part=main or part=early (e.g. #lastchristmas). Political,
LIVE-incentive and unlicensed-IP tags should stay out of the pack, or be
scored low with a written reason. The builder itself does not auto-invent
new CC memes; it will, however, attach rank/posts/views and any detail
curves to whatever cc_hashtags the pack already declared.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths as P  # noqa: E402


def _load_reportlib():
    P.prepare_reportlib()
    try:
        from reportlib.cc_lib import analyze_cc
        from reportlib.cc_trends import load_cc_trends
        from reportlib.charts import setup_font, chart_meme_heat_panel, chart_cc_hashtag_trend
        from reportlib.docx_v5 import build_docx_v5
        from reportlib.heat_lib import load_heat
        from reportlib.remix_lib import load_remix_csv, summarize_remixes
    except ImportError as exc:
        raise SystemExit(
            "reportlib is not on PYTHONPATH. Set paths.reportlib in config/settings.yaml "
            "or keep the package at /workspace/lark. "
            f"Original error: {exc}"
        ) from exc
    return {
        "analyze_cc": analyze_cc,
        "load_cc_trends": load_cc_trends,
        "setup_font": setup_font,
        "chart_meme_heat_panel": chart_meme_heat_panel,
        "chart_cc_hashtag_trend": chart_cc_hashtag_trend,
        "build_docx_v5": build_docx_v5,
        "load_heat": load_heat,
        "load_remix_csv": load_remix_csv,
        "summarize_remixes": summarize_remixes,
    }


def _slug(text: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "chart"


def load_pack(path: str) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not raw.get("memes"):
        raise SystemExit("pack JSON has no memes")
    for m in raw["memes"]:
        s = m.get("scores") or {}
        need = ["热度", "趋势", "分享率", "竞争", "窗口", "total"]
        missing = [k for k in need if k not in s]
        if missing:
            raise SystemExit(f"{m.get('name')}: scores missing {missing}")
        calc = sum(int(s[k]) for k in ["热度", "趋势", "分享率", "竞争", "窗口"])
        if calc != int(s["total"]):
            raise SystemExit(f"{m.get('name')}: total {s['total']} != {calc}")
    return raw


def make_charts(chart_dir: Path, font: str, heat_map: dict, cc_trends: dict, pack: dict, report_date: str) -> dict:
    lib = _load_reportlib()
    setup_font = lib["setup_font"]
    chart_meme_heat_panel = lib["chart_meme_heat_panel"]
    chart_cc_hashtag_trend = lib["chart_cc_hashtag_trend"]
    setup_font(font)
    chart_dir.mkdir(parents=True, exist_ok=True)
    paths = {"meme_heats": {}, "cc_trends": {}}
    wanted_heat = set()
    wanted_cc = set()
    for m in pack["memes"]:
        key = m.get("remix_key") or m.get("name")
        wanted_heat.add(key)
        wanted_heat.add(m.get("name"))
        for tag in m.get("cc_hashtags") or []:
            wanted_cc.add(tag.lstrip("#").lower())
    for name, mh in (heat_map or {}).items():
        if name not in wanted_heat:
            continue
        paths["meme_heats"][name] = chart_meme_heat_panel(
            chart_dir, mh, f"{report_date}-heat-{_slug(name)}.png"
        )
    for tag, tr in (cc_trends or {}).items():
        slug = tag.lstrip("#").lower()
        if slug not in wanted_cc:
            continue
        if not tr.has_series():
            continue
        paths["cc_trends"][slug] = chart_cc_hashtag_trend(
            chart_dir, tr, f"{report_date}-cc-trend-{_slug(slug)}.png"
        )
    return paths


def main():
    ap = argparse.ArgumentParser(description="Build the AI meme daily report")
    ap.add_argument("--date")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--md")
    ap.add_argument("--cc-csv")
    ap.add_argument("--cc-trends-csv")
    ap.add_argument("--remix-csv")
    ap.add_argument("--heat-json")
    ap.add_argument("--heat-csv")
    ap.add_argument("--backtest-json")
    ap.add_argument("--out-docx", help="default reports/YYYY-MM/YYYY-MM-DD-daily-report.docx")
    ap.add_argument("--chart-dir", help="default the month folder reports/YYYY-MM/")
    ap.add_argument("--font", default=str(P.FONT))
    P.add_lark_flags(ap)
    args = ap.parse_args()

    pack = load_pack(args.pack)
    report_date = args.date or pack.get("report_date")
    if not report_date:
        raise SystemExit("pass --date or set report_date in the pack")
    if not args.out_docx:
        args.out_docx = str(P.dated(report_date, "daily-report.docx"))
    if not args.chart_dir:
        args.chart_dir = str(P.month_dir(report_date))
    if not args.md:
        default_md = P.dated(report_date, "daily-report.md")
        if default_md.exists():
            args.md = str(default_md)
    Path(args.out_docx).parent.mkdir(parents=True, exist_ok=True)

    lib = _load_reportlib()
    remix_summary = {}
    if args.remix_csv:
        remix_summary = lib["summarize_remixes"](lib["load_remix_csv"](args.remix_csv))

    heat_path = args.heat_json or args.heat_csv
    heat_map = lib["load_heat"](heat_path) if heat_path else {}

    cc_analysis = lib["analyze_cc"](args.cc_csv) if args.cc_csv else None
    cc_trends = lib["load_cc_trends"](args.cc_trends_csv) if args.cc_trends_csv else {}

    backtest = {}
    if args.backtest_json:
        backtest = json.loads(Path(args.backtest_json).read_text(encoding="utf-8"))
        by_name = {r.get("meme"): r for r in (backtest.get("per_meme") or [])}
        default_line = (pack.get("backtest") or {}).get("note_zh") or "D+3 回测要到 11/13 才有首批对/错判断。"
        for m in pack["memes"]:
            rec = by_name.get(m["name"]) or {}
            m["backtest_line"] = rec.get("card_line_zh") or default_line

    charts = make_charts(Path(args.chart_dir), args.font, heat_map, cc_trends, pack, report_date)
    path = lib["build_docx_v5"](
        pack, remix_summary, heat_map, cc_analysis, cc_trends, charts,
        args.out_docx, report_date, backtest=backtest,
    )
    print("DOCX", path)
    print("MEMES", len(pack["memes"]))
    print("CHART meme_heats", charts["meme_heats"])
    print("CHART cc_trends", charts["cc_trends"])
    ranked = sorted(pack["memes"], key=lambda m: (-m["scores"]["total"], m["name"]))
    for i, m in enumerate(ranked, 1):
        s = m["scores"]
        print(f"RANK {i:2d} {s['total']:3d} {m['verdict']} {m['name']} "
              f"热{s['热度']} 趋{s['趋势']} 分{s['分享率']} 竞{s['竞争']} 窗{s['窗口']} "
              f"{m.get('part')} {m.get('window')}")
    if P.lark_enabled(args.sync_lark, args.no_lark):
        print("Lark sync enabled. This script only wrote files. Next: python scripts/sync_lark.py --sync-lark --as-of", report_date)
    else:
        print(P.lark_disabled_message())


if __name__ == "__main__":
    main()
