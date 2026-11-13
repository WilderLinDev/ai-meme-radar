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
from ..config import Paths
from ..decisions import all_effective, is_key, tracked_latest
from ..gefei.sync import credits_spent
from ..research.ingest import current_links
from ..research.metrics import pct as pct_change
from .common import (CONFIDENCE_ZH, DECISION_ZH, FIELD_ZH, LIFECYCLE_ZH, OUTCOME_ZH, attrs, bullets, dimension_table, name_of,
                     num, pct, write_report)

BIG_MOVE = 0.30
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
DECISION_ORDER = {"build": 0, "validate": 1, "monitor": 2, "skip": 3}


def _state_record(conn, st: dict, day: date) -> dict:
    return {k: st[k] for k in ("lifecycle", "decision", "priority", "confidence", "assessed_day", "revision")} | {
        "tracked_value": tracked_latest(conn, st, day), "overrides": len(st["overrides"])}


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
    retry = db.one(conn, "SELECT COUNT(*) AS n FROM sync_items WHERE status IN ('pending','failed')")
    if not new and not db.one(conn, "SELECT 1 FROM api_calls WHERE run_day=? AND purpose LIKE 'sync:%'",
                              (day.isoformat(),)):
        return ""
    names = {"keywords": "新词", "launches": "新站", "hosted": "网站发现"}
    parts = "，".join(f"{names.get(r['service'], r['service'])} {r['n']} 批" for r in new) or "无新批次"
    return f"哥飞数据同步：今日首次入库 {parts}；待重试单元 {retry['n'] if retry else 0} 个。"


def render(conn: sqlite3.Connection, day: date, paths: Paths) -> tuple[str, list[dict]]:
    states = all_effective(conn, day)
    links = current_links(conn)
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
        now_v, old_v = tracked_latest(conn, st, day), p.get("tracked_value")
        if now_v is not None and old_v:
            ch = pct_change(now_v, old_v)
            if ch is not None and abs(ch) >= BIG_MOVE:
                notes.append(f"跟踪指标 {num(old_v)} → {num(now_v)}（{pct(ch)}）【已核实·本地快照】")
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

    # backtest
    sm = backtest.summary(conn)
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
    gaps = db.rows(conn, "SELECT * FROM gaps WHERE day=? ORDER BY source", (day.isoformat(),))
    out += ["## 数据缺口", ""] + ([f"- {g['source']}：{g['note']}" for g in gaps] or ["今天没有记录缺口。"]) + [""]
    calls = db.one(conn, "SELECT COUNT(*) AS n FROM api_calls WHERE run_day=?", (day.isoformat(),))
    out += ["## 数据与口径", "",
            f"- 哥飞 API：今日 {calls['n'] if calls else 0} 次调用，实际扣除 {num(credits_spent(conn, day))} 积分【已核实·接口返回】。",
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
