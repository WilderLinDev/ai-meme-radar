"""The daily report: what changed and what to act on, not a re-print of everything.

Change detection compares today's effective state of each assessed entity with
the state saved by the previous report. Entities that did not change get one
line in the last section; only key opportunities and changes are expanded.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from .. import backtest, db
from ..config import Paths, end_of
from ..decisions import all_effective, is_key, tracked_point
from ..research.metrics import identity_key
from ..research.ingest import current_links
from ..research.metrics import pct as pct_change
from .common import (CONFIDENCE_ZH, cell, DECISION_ZH, FIELD_ZH, LIFECYCLE_ZH, OUTCOME_ZH, attrs, bullets, dimension_table, name_of,
                     num, pct, write_report)

BIG_MOVE = 0.30
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
DECISION_ORDER = {"build": 0, "validate": 1, "monitor": 2, "skip": 3}


def _state_record(conn, st: dict, day: date) -> dict:
    p = tracked_point(conn, st, day)  # only observations ingested by `day`
    return {k: st[k] for k in ("lifecycle", "decision", "priority", "confidence", "assessed_day", "revision")} | {
        "tracked": {"value": p.value, "at": p.at, "ident": p.ident} if p else None,
        "overrides": len(st["overrides"])}


def tracked_move(prev: dict | None, cur: dict | None) -> tuple[float | None, str]:
    """Change between two report states' tracked observations, only when they measure the same thing.

    Returns (change, note). change is None when either side is missing, the identity is missing or
    differs (source, metric, unit, definition, region), or the old value is 0; the note says why.
    """
    if not prev or not cur:
        return None, ""
    a, b = identity_key(prev.get("ident")), identity_key(cur.get("ident"))
    if not a or not b:
        return None, "跟踪指标缺少口径信息，不计算变化"
    if a != b:
        return None, "跟踪指标口径与上次不同，不计算变化"
    if prev["at"] == cur["at"]:
        return None, ""
    return pct_change(cur["value"], prev["value"]), ""


def previous_states(conn: sqlite3.Connection, day: date) -> tuple[str | None, dict[str, dict]]:
    r = db.one(conn, "SELECT MAX(day) AS d FROM report_states WHERE day < ?", (day.isoformat(),))
    if not r or not r["d"]:
        return None, {}
    return r["d"], {x["entity"]: json.loads(x["state_json"])
                    for x in db.rows(conn, "SELECT * FROM report_states WHERE day=?", (r["d"],))}


def _related(conn, entity: str, links) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for (s, d, rel) in links:
        if entity in (s, d):
            other = d if s == entity else s
            out.setdefault(other.split(":", 1)[0], []).append(name_of(conn, other))
    return {k: sorted(set(v)) for k, v in out.items()}


def _sort(states: list[dict]) -> list[dict]:
    return sorted(states, key=lambda s: (PRIORITY_ORDER[s["priority"]], DECISION_ORDER[s["decision"]], s["entity"]))


def _full(conn, st: dict, links, day: date, paths: Paths) -> list[str]:
    b = st["body"]
    rel = _related(conn, st["entity"], links)
    out = [f"### {name_of(conn, st['entity'])}", "", f"**{attrs(st)}**", "", b["summary"], ""]
    if b.get("why_now"):
        out += [f"**为什么是现在**：{b['why_now']}", ""]
    out += [f"**判断理由**：{b['rationale']}", ""]
    out += dimension_table(b) + [""]
    names = {"trend": "关联趋势", "format": "内容格式", "keyword": "搜索词", "site": "相关网站/竞品"}
    for k, label in names.items():
        if rel.get(k):
            out.append(f"- {label}：{'、'.join(rel[k])}")
    if b.get("next_steps"):
        out += ["", "**下一步**："] + bullets(b["next_steps"])
    if b.get("open_questions"):
        out += ["", "**待解决问题**："] + bullets(b["open_questions"])
    if b.get("assumptions"):
        out += ["", "**推断与未验证假设**："] + bullets(b["assumptions"])
    for o in st["overrides"]:
        out.append(f"- 人工修改：{FIELD_ZH[o['field']]} {o['from']} → {o['to']}（{o['author']}：{o['reason']}）")
    for d in st["directions"]:
        out.append(f"- 研究方向（{d['author']}）：{d['note']}")
    if st["entity"].startswith("opportunity:") and is_key(st):
        oid = st["entity"].split(":", 1)[1]
        out += ["", f"深度报告：`reports/opportunities/{oid}/`"]
    if st["assessed_day"] != day.isoformat():
        out += ["", f"_沿用 {st['assessed_day']} 的判断，今日未重新评估。_"]
    return out + [""]


def _line(conn, st: dict, note: str = "") -> str:
    b = st["body"]
    tail = f"（{note}）" if note else ""
    return f"- **{name_of(conn, st['entity'])}** — {attrs(st)}。{b['summary']}{tail}"


def sync_note(conn: sqlite3.Connection, day: date) -> str:
    """Derived from the store, so rerunning a day renders the same text."""
    new = db.rows(conn, "SELECT service, COUNT(*) AS n FROM gefei_batches WHERE substr(first_seen_at,1,10)=?"
                        " GROUP BY service ORDER BY service", (day.isoformat(),))
    if not new and not db.one(conn, "SELECT 1 FROM api_calls WHERE run_day=? AND purpose LIKE 'sync:%'"
                                    " AND started_at <= ?", (day.isoformat(), end_of(day))):
        return ""
    names = {"keywords": "新词", "launches": "新站", "hosted": "网站发现"}
    parts = "，".join(f"{names.get(r['service'], r['service'])} {r['n']} 批" for r in new) or "无新批次"
    return f"哥飞数据同步：今日首次入库 {parts}。"


COVERAGE_ZH = {"covered": "已完成", "partial": "部分完成", "failed": "失败", "not_attempted": "未进行"}
SIGNALS_ZH = {"found": "有", "none": "无", "unknown": "未知"}


def coverage(conn: sqlite3.Connection, day: date) -> tuple[str, list[str]]:
    """(one-line summary, section lines) for the day's social research coverage."""
    r = db.one(conn, "SELECT * FROM research_days WHERE day=? AND updated_at <= ?", (day.isoformat(), end_of(day)))
    if not r:
        return "社交调研覆盖：未记录（今日 research.json 未入库）。", ["今日没有入库的 research.json，社交调研覆盖情况未知。"]
    cov = json.loads(r["social_coverage_json"])
    done = [c for c in cov if c["status"] == "covered"]
    other = [c for c in cov if c["status"] != "covered"]
    summary = f"社交调研覆盖：{len(done)}/{len(cov)} 个来源完成" + (
        "；未完成：" + "、".join(f"{c['platform']}（{COVERAGE_ZH[c['status']]}）" for c in other) if other else "") + "。"
    lines = ["| 来源 | 状态 | 时间窗 | 有用信号 | 说明 |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {c['platform']} | {COVERAGE_ZH[c['status']]} | {cell(c['window']) or '—'} | "
              f"{SIGNALS_ZH[c['signals']]} | {cell(c['note']) or '—'} |" for c in cov]
    if r["notes"].strip():
        lines += ["", f"调研备注：{r['notes'].strip()}"]
    return summary, lines


def render(conn: sqlite3.Connection, day: date, paths: Paths) -> tuple[str, list[dict]]:
    states = all_effective(conn, day)
    links = current_links(conn, as_of=day)  # every query below is bounded by the report day
    prev_day, prev = previous_states(conn, day)
    covered: set[str] = set()

    def changed(st) -> bool:
        p = prev.get(st["entity"])
        rec = _state_record(conn, st, day)
        return p is None or any(p.get(k) != rec.get(k) for k in ("lifecycle", "decision", "priority", "confidence",
                                                                  "assessed_day", "overrides"))

    out = [f"# AI 创作机会日报 · {day.isoformat()}", "",
           f"> 对比基准：{prev_day or '无（首份日报）'}。本日报由本地 Markdown 为准，飞书为发布副本。", ""]
    note = sync_note(conn, day)
    if note:
        out += [f"> {note}", ""]
    cov_summary, cov_lines = coverage(conn, day)
    out += [f"> {cov_summary}", ""]

    # 1. key opportunities
    key = _sort([s for s in states if is_key(s)])
    out += ["## 1. 今日最值得关注的机会", ""]
    if not key:
        out += ["今天没有处于「立即做 / 验证」或 P0–P1 的模板机会。", ""]
    for st in key:
        covered.add(st["entity"])
        if changed(st):
            out += _full(conn, st, links, day, paths)
        else:
            out += [_line(conn, st, "较上次日报无变化，详见深度报告"), ""]

    # 2. new early signals
    new = [s for s in states if s["entity"] not in covered and
           db.one(conn, "SELECT 1 FROM entities WHERE kind=? AND id=? AND first_seen_day=?",
                  (*s["entity"].split(":", 1), day.isoformat()))]
    out += ["## 2. 新发现的早期信号", ""]
    out += [_line(conn, s) for s in _sort(new)] or ["今天没有新登记的趋势或机会。"]
    covered |= {s["entity"] for s in new}
    out.append("")

    # 3. important trend changes
    moves = []
    for st in states:
        p = prev.get(st["entity"])
        if not p or st["entity"] in covered:
            continue
        notes = []
        if p["lifecycle"] != st["lifecycle"]:
            notes.append(f"生命周期 {LIFECYCLE_ZH[p['lifecycle']]} → {LIFECYCLE_ZH[st['lifecycle']]}")
        cur = _state_record(conn, st, day)["tracked"]
        ch, why = tracked_move(p.get("tracked"), cur)
        if ch is not None and abs(ch) >= BIG_MOVE:
            i = cur["ident"]
            notes.append(f"跟踪指标（{i['source']} {i['metric']} {i['region'] or '—'}）{num(p['tracked']['value'])} → "
                         f"{num(cur['value'])}（{pct(ch)}）【已核实·本地快照】")
        elif why and p.get("tracked"):
            notes.append(why)
        if notes:
            moves.append((st, "；".join(notes)))
    out += ["## 3. 重要趋势变化", ""]
    out += [_line(conn, st, n) for st, n in moves] or ["与上一份日报相比，没有生命周期变化或 ±30% 以上的指标变动。"]
    covered |= {st["entity"] for st, _ in moves}
    out.append("")

    # 4. decision changes
    dchanges = []
    for st in states:
        p = prev.get(st["entity"])
        if p and (p["decision"] != st["decision"] or p["priority"] != st["priority"]):
            who = "人工" if st["overrides"] else "Agent"
            dchanges.append(f"- **{name_of(conn, st['entity'])}**：{DECISION_ZH[p['decision']]}/{p['priority']} → "
                            f"{DECISION_ZH[st['decision']]}/{st['priority']}（{who}）。{st['body']['rationale']}")
    out += ["## 4. 决策变化", ""] + (dchanges or ["没有决策或优先级变化。"]) + [""]

    # 5. needs validation
    val = [s for s in _sort(states) if s["decision"] == "validate"]
    out += ["## 5. 需要进一步验证的机会", ""]
    if not val:
        out.append("没有处于「验证」状态的对象。")
    for st in val:
        b = st["body"]
        out.append(f"- **{name_of(conn, st['entity'])}**（{st['priority']}，证据可信度{CONFIDENCE_ZH[st['confidence']]}）")
        for q in b.get("open_questions", []):
            out.append(f"  - 待验证：{q}")
        for n in b.get("next_steps", []):
            out.append(f"  - 下一步：{n}")
    out.append("")

    # 6. other noteworthy
    rest = [s for s in _sort(states) if s["entity"] not in covered and s["decision"] != "skip"]
    out += ["## 6. 其他值得关注的趋势", ""]
    out += [_line(conn, s, "" if changed(s) else "无变化") for s in rest] or ["无。"]
    skipped = [s for s in states if s["decision"] == "skip" and s["entity"] not in covered]
    if skipped:
        out += ["", "不做：" + "、".join(name_of(conn, s["entity"]) for s in _sort(skipped))]
    out.append("")

    out += ["## 社交调研覆盖", ""] + cov_lines + [""]

    # backtest
    sm = backtest.summary(conn, as_of=day)
    out += ["## 回测", ""]
    for system, label in (("lifecycle", "生命周期预测"), ("decision", "模板机会决策")):
        s = sm[system]
        rate = f"{s['rate'] * 100:.0f}%（{s['good']}/{s['scored']}）" if s["rate"] is not None else "尚无可评估样本"
        counts = "，".join(f"{OUTCOME_ZH.get(k, k)} {v}" for k, v in sorted(s["counts"].items()))
        out.append(f"- {label}：{rate}。{counts or '暂无记录'}")
    for r in backtest.resolved_on(conn, day):
        out.append(f"  - 今日结算：{name_of(conn, r['entity'])}（{r['assessed_day']} 判断 {r['detail']}）"
                   f" {num(r['baseline_value'])} → {num(r['outcome_value'])}（{pct(r['change_pct'])}）："
                   f"{OUTCOME_ZH[r['outcome']]}")
    out.append("")

    # gaps & sources
    gaps = db.rows(conn, "SELECT * FROM gaps WHERE day=? AND ingested_at <= ? ORDER BY source, note",
                   (day.isoformat(), end_of(day)))
    out += ["## 数据缺口", ""] + ([f"- {g['source']}：{g['note']}" for g in gaps] or ["今天没有记录缺口。"]) + [""]
    calls = db.one(conn, "SELECT COUNT(*) AS n, COALESCE(SUM(credits_charged), 0) AS c FROM api_calls"
                         " WHERE run_day=? AND started_at <= ? AND purpose != 'preflight'",
                   (day.isoformat(), end_of(day)))
    out += ["## 数据与口径", "",
            f"- 哥飞 API：今日 {calls['n'] if calls else 0} 次调用，实际扣除 {num(float(calls['c']) if calls else 0.0)} 积分【已核实·接口返回】（不含开工预检的余额与权限查询）。",
            "- 流量、点击为第三方估算，不等于实际营收；收入数据中的访问量是支付渠道引荐估算。",
            "- 数字标注：【已核实】【第三方读数】【估算】；缺失的序列不插值。", ""]
    records = [{"entity": s["entity"], **_state_record(conn, s, day)} for s in states]
    return "\n".join(out), records


def build(conn: sqlite3.Connection, day: date, paths: Paths) -> bool:
    text, records = render(conn, day, paths)
    with db.tx(conn):
        conn.execute("DELETE FROM report_states WHERE day=?", (day.isoformat(),))
        for r in records:
            conn.execute("INSERT INTO report_states (day, entity, state_json) VALUES (?,?,?)",
                         (day.isoformat(), r.pop("entity"), db.dumps(r)))
        return write_report(conn, f"daily/{day.isoformat()}", "daily", day.isoformat(), None,
                            f"AI 创作机会日报 {day.isoformat()}", paths.daily_report(day), text)
