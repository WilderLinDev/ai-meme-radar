"""Labels and small formatters shared by the daily and in-depth reports."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .. import db
from ..config import now_iso
from ..research.models import DIMENSIONS
from ..text import parse_ref

LIFECYCLE_ZH = {"early_signal": "早期信号", "emerging": "上升期", "proven": "已验证", "fading": "衰退期"}
DECISION_ZH = {"build": "立即做", "validate": "验证", "monitor": "观察", "skip": "不做"}
CONFIDENCE_ZH = {"high": "高", "medium": "中", "low": "低"}
LEVEL_ZH = {"high": "高", "medium": "中", "low": "低", "unknown": "未知"}
DIM_ZH = {"social_momentum": "社交势能", "search_demand": "搜索需求", "audience_participation": "用户参与",
          "template_potential": "模板潜力", "ai_feasibility": "AI 可行性", "competition": "竞争强度",
          "timing": "时机"}
KIND_ZH = {"trend": "趋势", "format": "格式", "opportunity": "模板机会", "keyword": "关键词", "site": "网站"}
CHANNEL_ZH = {"social": "社交", "search": "搜索", "product": "产品", "market": "市场"}
OUTCOME_ZH = {"hit": "命中", "miss": "未命中", "supported": "得到支持", "not_supported": "未得到支持",
              "ok": "无遗漏", "missed_upside": "错过上涨", "missed": "错过", "correct": "正确",
              "pending": "待观察", "no_data": "无数据", "unscorable": "无法评估"}
FIELD_ZH = {"decision": "决策", "priority": "优先级", "lifecycle": "生命周期"}


def name_of(conn: sqlite3.Connection, entity: str) -> str:
    kind, ident = parse_ref(entity)
    if kind in ("keyword", "site"):
        return ident
    r = db.one(conn, "SELECT name FROM entities WHERE kind=? AND id=?", (kind, ident))
    return r["name"] if r else ident


def attrs(state: dict) -> str:
    return (f"{LIFECYCLE_ZH[state['lifecycle']]} · {DECISION_ZH[state['decision']]} · {state['priority']} · "
            f"证据可信度{CONFIDENCE_ZH[state['confidence']]}")


def num(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        return f"{v:,}"
    return f"{v:,.2f}"


def pct(v) -> str:
    return "—" if v is None else f"{v * 100:+.0f}%"


def cell(text) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def dimension_table(body: dict) -> list[str]:
    lines = ["| 维度 | 判断 | 依据 |", "| --- | --- | --- |"]
    for d in DIMENSIONS:
        dim = body["dimensions"][d]
        refs = f"（证据：{', '.join(dim['evidence'])}）" if dim.get("evidence") else ""
        lines.append(f"| {DIM_ZH[d]} | {LEVEL_ZH[dim['level']]} | {cell(dim['note'])}{refs} |")
    return lines


def bullets(items: list[str], empty: str = "") -> list[str]:
    if not items:
        return [empty] if empty else []
    return [f"- {i}" for i in items]


def write_report(conn: sqlite3.Connection, key: str, kind: str, day: str, entity: str | None, title: str,
                 path: Path, text: str) -> bool:
    """Write the Markdown file and index it. Returns True when content changed."""
    h = db.sha(text)
    prev = db.one(conn, "SELECT content_hash FROM reports WHERE key=?", (key,))
    if prev and prev["content_hash"] == h and path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    conn.execute("INSERT OR REPLACE INTO reports (key, kind, day, entity, title, path, content_hash, written_at)"
                 " VALUES (?,?,?,?,?,?,?,?)", (key, kind, day, entity, title, str(path), h, now_iso()))
    return True


def evidence_rows(conn: sqlite3.Connection, entities: list[str], per_entity: int = 12) -> list[str]:
    """Evidence ledger for exactly these entities (latest `per_entity` each), in the given entity order."""
    rows = []
    for ent in entities:
        rows += db.rows(conn, "SELECT * FROM evidence WHERE entity=? ORDER BY collected_at DESC, id DESC LIMIT ?",
                        (ent, per_entity))
    if not rows:
        return ["暂无已入库的证据。"]
    out = ["| 引用 | 对象 | 渠道 | 来源 | 指标 | 数值 | 地区 | 样本 | 采集时间 | 标注 | 可信度 | 口径 |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for e in rows:
        src = f"[{cell(e['source'])}]({e['url']})" if e["url"] else cell(e["source"])
        if e["api_call_id"]:
            src += f"（call:{e['api_call_id']}）"
        value = (num(e["value"]) + (f" {e['unit']}" if e["unit"] else "")) if e["value"] is not None else cell(e["note"])
        kind = e["entity"].split(":", 1)[0]
        out.append(f"| {cell(e['ref'] or '—')} | {KIND_ZH[kind]}·{cell(name_of(conn, e['entity']))} |"
                   f" {CHANNEL_ZH[e['channel']]} | {src} | {cell(e['metric'])} | {value} | {e['region'] or '—'} |"
                   f" {e['sample_size'] or '—'} | {e['collected_at'][:16]} | 【{e['tag']}】 |"
                   f" {CONFIDENCE_ZH[e['confidence']]} | {cell(e['metric_definition'])} |")
    return out


def loads(s: str | None):
    return json.loads(s) if s else None
