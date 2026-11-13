"""In-depth report for each key opportunity (build / validate, or P0 / P1).

The agent writes the twelve narrative sections in its assessment (`deep`);
code adds the attribute line, the dimension table, the evidence ledger, links,
search series, human changes and backtest history. One file per opportunity per
assessment day; the Lark copy of an opportunity is one document kept current.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from .. import db
from ..config import Paths
from ..decisions import all_effective, is_key
from ..research import metrics
from ..research.ingest import current_links
from ..research.models import DEEP_SECTIONS
from .common import (FIELD_ZH, KIND_ZH, OUTCOME_ZH, attrs, bullets, cell, dimension_table, evidence_rows, name_of,
                     num, pct, write_report)

SECTION_ZH = {"trend_overview": "趋势概览", "why_now": "为什么是现在", "social_evidence": "社交证据",
              "search_demand": "搜索需求", "audience_behavior": "用户行为", "format_analysis": "格式分析",
              "product_opportunity": "产品机会", "competition": "竞争", "ai_feasibility": "AI 可行性",
              "recommendation": "建议", "evidence_confidence": "证据可信度", "remaining_questions": "仍待回答的问题"}
FOCUS_ZH = {"early_signal": "早期信号：重点看新发现、初步证据和潜力。",
            "emerging": "上升期：重点看增长速度、扩散范围和验证机会。",
            "proven": "已验证：重点看市场需求、竞争和产品化潜力。",
            "fading": "衰退期：重点看下滑原因、剩余窗口和可复用价值。"}


def _neighbours(entity: str, links) -> list[tuple[str, str]]:
    return sorted({(d if s == entity else s, rel) for (s, d, rel) in links if entity in (s, d)})


def render(conn: sqlite3.Connection, st: dict, day: date) -> str:
    links = current_links(conn)
    ent = st["entity"]
    b = st["body"]
    nb = _neighbours(ent, links)
    # one hop further: trends behind this opportunity's formats
    second = []
    for other, _ in nb:
        if other.startswith("format:"):
            second += [o for o, _ in _neighbours(other, links) if o.startswith("trend:")]
    related = sorted({o for o, _ in nb} | set(second))
    out = [f"# 深度研究：{name_of(conn, ent)}", "",
           f"**{attrs(st)}** · 评估日 {st['assessed_day']}（第 {st['revision']} 版）", "",
           f"> 研究重点（{FOCUS_ZH[st['lifecycle']]}）", "", b["summary"], ""]
    for sec in DEEP_SECTIONS:
        text = b.get("deep", {}).get(sec, "").strip()
        out += [f"## {SECTION_ZH[sec]}", "", text or "_本次评估未填写。_", ""]
        if sec == "evidence_confidence":
            out += dimension_table(b) + [""]
            if b.get("assumptions"):
                out += ["**推断与未验证假设**："] + bullets(b["assumptions"]) + [""]
    out += ["## 关联对象", ""]
    for other, rel in nb:
        kind = other.split(":", 1)[0]
        out.append(f"- {KIND_ZH[kind]}：{name_of(conn, other)}（{rel}）")
    for t in sorted(set(second)):
        out.append(f"- 经由格式关联的趋势：{name_of(conn, t)}")
    out += ["", "## 证据清单", ""] + evidence_rows(conn, [ent, *[r for r in related if r.split(':')[0] in
                                                                ('trend', 'format', 'opportunity')]]) + [""]
    kws = [o.split(":", 1)[1] for o, _ in nb if o.startswith("keyword:")]
    if kws:
        out += ["## 哥飞关键词序列", "", "| 关键词 | 点数 | 最新 heat_ratio | 前值 | 变化 | 峰值 | 距峰值 |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for kw in kws:
            s = metrics.stats(kw, metrics.keyword_heat_series(conn, kw))
            if s:
                out.append(f"| {cell(kw)} | {s.n} | {num(s.latest)} | {num(s.previous)} | {pct(s.change_pct)} |"
                           f" {num(s.peak)} | {pct(s.from_peak_pct)} |")
            else:
                out.append(f"| {cell(kw)} | 0 | — | — | — | — | — |")
        out += ["", "heat_ratio 是哥飞相对 GPTs 基准词的热度倍数，不是搜索量【第三方读数】。", ""]
    hist = db.rows(conn, "SELECT * FROM feedback WHERE entity=? ORDER BY at", (ent,))
    if hist:
        out += ["## 人工修改记录", ""]
        for f in hist:
            label = FIELD_ZH.get(f["field"], f["field"])
            out.append(f"- {f['at'][:16]} {f['author']}：{label} {f['old_value'] or ''} → {f['new_value']}（{f['reason']}）")
        out.append("")
    bt = db.rows(conn, "SELECT b.*, a.day FROM backtest_results b JOIN assessments a ON a.id=b.assessment_id"
                       " WHERE a.entity=? ORDER BY a.day, b.system", (ent,))
    if bt:
        out += ["## 回测记录", "", "| 评估日 | 体系 | 基线 | 结果值 | 变化 | 结论 |", "| --- | --- | --- | --- | --- | --- |"]
        for r in bt:
            out.append(f"| {r['day']} | {'生命周期' if r['system'] == 'lifecycle' else '决策'} | {num(r['baseline_value'])} |"
                       f" {num(r['outcome_value'])} | {pct(r['change_pct'])} | {OUTCOME_ZH[r['outcome']]} |")
        out.append("")
    return "\n".join(out)


def build(conn: sqlite3.Connection, day: date, paths: Paths) -> list[str]:
    """Write a deep report for every key opportunity assessed today, or never written before."""
    written = []
    for st in all_effective(conn, day):
        if not is_key(st):
            continue
        oid = st["entity"].split(":", 1)[1]
        have = db.one(conn, "SELECT 1 FROM reports WHERE kind='opportunity' AND entity=?", (st["entity"],))
        if st["assessed_day"] != day.isoformat() and have:
            continue
        text = render(conn, st, day)
        key = f"opportunity/{oid}/{day.isoformat()}"
        if write_report(conn, key, "opportunity", day.isoformat(), st["entity"], f"深度研究：{name_of(conn, st['entity'])}",
                        paths.opportunity_report(oid, day), text):
            written.append(key)
    return written
