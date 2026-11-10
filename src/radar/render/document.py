"""Turn a meme pack into report blocks.

Length follows the verdict: `make` gets the full seven blocks, `watch` a short
card, `skip` one table row. Early signals are short cards unless they are `make`.
"""
from __future__ import annotations

from pathlib import Path

from ..judgments import DIMENSION_ZH, DIMENSIONS, VERDICT_ZH
from ..pack import Pack, PackMeme
from .blocks import Bullets, Card, Code, Document, Heading, Image, Link, Para, Ref, Table

EVIDENCE_LEGEND = ("【已核实】＝从平台公开统计亲自读到；【第三方读数】＝ViralRemix / Turnly / Creative Center 等追踪站；"
                   "【估算】＝推算值。X 日发帖、ViralRemix 日新视频、Creative Center 指数口径不同，不能横比。")


def fmt_count(n: float | None) -> str:
    if n is None:
        return "—"
    for floor, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= floor:
            return f"{n / floor:.1f}{suf}"
    return f"{n:g}"


def anchor(m: PackMeme) -> str:
    return "meme-" + m.id


def score_short(m: PackMeme) -> str:
    return f"{m.facts.total}（{m.judgment.scores.short()}）"


def verdict_text(m: PackMeme) -> str:
    j, f = m.judgment, m.facts
    text = VERDICT_ZH[j.verdict]
    if f.suggested_verdict and f.suggested_verdict != j.verdict:
        text += f"（按分数应为{VERDICT_ZH[f.suggested_verdict]}，否决：{j.override_reason}）"
    return text


def days_text(m: PackMeme) -> str:
    return f"{m.facts.days_hot} 天" if m.facts.days_hot is not None else "未核实"


def movement_text(m: PackMeme) -> str:
    mv = m.facts.movement
    if not mv:
        return "首次出现"
    delta = (m.facts.total or 0) - mv.prev_total
    verdict = VERDICT_ZH.get(mv.prev_verdict, mv.prev_verdict)
    change = "结论不变" if mv.prev_verdict == m.judgment.verdict else f"结论 {verdict} → {VERDICT_ZH[m.judgment.verdict]}"
    return f"相对 {mv.prev_date:%m-%d}：{mv.prev_total} → {m.facts.total}（{delta:+d}），{change}"


def build_document(pack: Pack, charts: dict[str, list[tuple[Path, str]]]) -> Document:
    doc = Document(title=f"AI 视频梗日报 {pack.date}",
                   subtitle="只回答一件事：今天该为哪个梗做 AI 模板。")
    full = {m.id for m in pack.memes if m.judgment.verdict == "make"}
    carded = {m.id for m in pack.memes if m.judgment.verdict == "watch"}

    # 一、总排名
    doc.add(Heading(1, "一、总排名"))
    rows = []
    for i, m in enumerate(pack.ranked(), 1):
        target = anchor(m) if m.id in full | carded else "skip-table"
        label = m.facts.display + (f" 【{m.facts.source_label}】" if m.facts.source_label else "")
        if m.judgment.part == "early":
            label += " 【早期信号】"
        rows.append([str(i), Ref(label, target), score_short(m), verdict_text(m),
                     m.judgment.window_note or "—", days_text(m), m.facts.peak_label])
    doc.add(Table(["排名", "梗", "综合评分", "结论", "窗口期", "已火天数", "高峰状态"], rows),
            Para(EVIDENCE_LEGEND, muted=True))

    doc.add(Heading(2, "回测"))
    doc.add(Para(pack.backtest.text_zh() if pack.backtest else "今天没有回测。"))
    doc.add(Para("规则见 docs/scoring.md：「做」看 D+3 主热度是否严格高于基线，连续推荐只计首日；"
                 "观望/不做若 D+3 主热度比基线高 20% 以上记为漏判。", muted=True))

    if pack.gaps or pack.notes:
        doc.add(Heading(2, "今日缺口与说明"))
        doc.add(Bullets([(g.source + "：", g.note) for g in pack.gaps] + [(None, n) for n in pack.notes]))
    if pack.cc_lists:
        doc.add(Para("今日 Creative Center 榜：" + "、".join(pack.cc_lists) + "（行业 News & Entertainment；NL 不提供，已跳过）。",
                     muted=True))

    # 二、主榜
    main = pack.ranked("main")
    early = pack.ranked("early")
    doc.add(Heading(1, "二、逐个梗"))
    make_main = [m for m in main if m.judgment.verdict == "make"]
    watch_main = [m for m in main if m.judgment.verdict == "watch"]
    doc.add(Heading(2, "2.1 做"))
    if not make_main:
        doc.add(Para("今天主榜没有判「做」的梗。"))
    for i, m in enumerate(make_main, 1):
        _full_section(doc, m, f"2.1.{i}", charts.get(m.id, []))
    doc.add(Heading(2, "2.2 观望"))
    if not watch_main:
        doc.add(Para("今天主榜没有判「观望」的梗。"))
    for i, m in enumerate(watch_main, 1):
        _card_section(doc, m, f"2.2.{i}")
    doc.add(Heading(2, "2.3 不做", anchor="skip-table"))
    skips = [m for m in pack.ranked() if m.judgment.verdict == "skip"]
    if skips:
        doc.add(Table(["梗", "综合评分", "理由"],
                      [[m.facts.display, score_short(m), m.judgment.reason] for m in skips]))
    else:
        doc.add(Para("今天没有判「不做」的梗。"))
    if pack.excluded_hashtags:
        doc.add(Heading(2, "2.4 排除的 Creative Center 话题"))
        doc.add(Table(["理由", "话题"],
                      [[g.reason, " ".join("#" + t for t in g.tags)] for g in pack.excluded_hashtags]))

    # 三、早期信号
    doc.add(Heading(1, "三、早期信号"))
    shown = [m for m in early if m.judgment.verdict != "skip"]
    if not shown:
        doc.add(Para("今天没有值得单列的早期信号。"))
    for i, m in enumerate(shown, 1):
        if m.judgment.verdict == "make":
            _full_section(doc, m, f"3.{i}", charts.get(m.id, []))
        else:
            _card_section(doc, m, f"3.{i}")
    return doc


def _conclusion_rows(m: PackMeme) -> list[tuple[str, str]]:
    j, f = m.judgment, m.facts
    return [
        ("结论", verdict_text(m)),
        ("综合评分", f"{f.total}/100　" + "　".join(f"{DIMENSION_ZH[d]} {getattr(j.scores, d).score}" for d in DIMENSIONS)),
        ("窗口期", j.window_note or "—"),
        ("起火日期", (j.ignite_date.isoformat() if j.ignite_date else "未核实") + (f"（{j.ignite_note}）" if j.ignite_note else "")),
        ("已火天数", days_text(m)),
        ("是否仍在高峰", f"{f.peak_label}；口径：{f.primary_label}"),
        ("变动", movement_text(m)),
        ("回测", f.backtest_line),
        ("一句理由", j.reason),
    ]


def _card_section(doc: Document, m: PackMeme, number: str) -> None:
    j = m.judgment
    doc.add(Heading(3, f"{number}  {m.facts.display}", anchor=anchor(m)))
    rows = _conclusion_rows(m)
    if j.watch_for:
        rows.append(("盯什么", j.watch_for))
    doc.add(Card(rows, tone=j.verdict))
    links = [(None, Link(l.label, l.url)) for l in j.links[:3]]
    if links:
        doc.add(Bullets(links))


def _full_section(doc: Document, m: PackMeme, number: str, charts: list[tuple[Path, str]]) -> None:
    j, f = m.judgment, m.facts
    doc.add(Heading(3, f"{number}  {f.display}", anchor=anchor(m)))

    doc.add(Heading(4, "结论卡"))
    rows = _conclusion_rows(m)
    notes = "；".join(f"{DIMENSION_ZH[d]}：{getattr(j.scores, d).note}" for d in DIMENSIONS if getattr(j.scores, d).note)
    if notes:
        rows.append(("评分依据", notes))
    doc.add(Card(rows, tone=j.verdict))

    doc.add(Heading(4, "是什么 + 链接"))
    if j.what:
        doc.add(Para(j.what))
    items: list = []
    if j.origin:
        items.append(("出处：", j.origin))
    items += [(None, Link(l.label, l.url)) for l in j.links]
    seen = {l.url for l in j.links}
    for r in f.top_remixes[:5]:
        if r.link not in seen:
            items.append((None, Link(f"示例二创 @{r.creator or '—'} · {r.platform} · {fmt_count(r.views)} 播放", r.link)))
    if items:
        doc.add(Bullets(items))

    doc.add(Heading(4, "热度曲线"))
    heat_items = [("主热度口径：", f.primary_label), ("当前位置：", f.peak_label)]
    if j.heat_note:
        heat_items.append(("说明：", j.heat_note))
    doc.add(Bullets(heat_items))
    for path, caption in charts:
        doc.add(Image(path, caption))
    if f.cc:
        doc.add(Table(["话题", "地区", "近 7 日（排名 · 帖 / 播放）", "近 30 日（排名 · 帖 / 播放）", "7 日 vs 30 日"],
                      [["#" + c.hashtag, c.region,
                        f"第{c.rank_7d} · {fmt_count(c.posts_7d)} / {fmt_count(c.views_7d)}" if c.rank_7d else "未上榜",
                        f"第{c.rank_30d} · {fmt_count(c.posts_30d)} / {fmt_count(c.views_30d)}" if c.rank_30d else "未上榜",
                        c.flag] for c in f.cc],
                      caption="Creative Center News & Entertainment 榜【第三方读数】。NEW_7D / FADE_30D / SUSTAIN 是 7 日榜与 30 日榜是否出现的代理。"))
    if f.audience:
        doc.add(Bullets(_audience_items(m)))

    doc.add(Heading(4, "二创分享率"))
    if f.share:
        doc.add(Bullets([(None, s.label_zh) for s in f.share]))
    else:
        doc.add(Para("没有读到高播二创样本，分享率按保守分处理。"))
    if f.top_remixes:
        doc.add(Table(["平台", "创作者 / 视频", "日期", "播放", "赞", "分享", "分享率", "AI"],
                      [[r.platform, Link("@" + (r.creator or "打开视频"), r.link),
                        r.posted_on.isoformat() if r.posted_on else "—", fmt_count(r.views), fmt_count(r.likes),
                        fmt_count(r.shares), f"{r.share_rate * 100:.2f}%" if r.share_rate is not None else "—", r.is_ai]
                       for r in f.top_remixes],
                      caption="高播二创，已排除原视频，按播放排序。TikTok 分享与 X 转发不横比。数字【已核实】。"))
    if j.share_note:
        doc.add(Para(j.share_note))

    doc.add(Heading(4, "竞争与模板"))
    c = j.competition
    comp: list = []
    if c.capcut:
        comp.append(("CapCut：", c.capcut))
    if c.capcut_url:
        comp.append((None, Link("CapCut 模板页", c.capcut_url)))
    comp += [(None, Link(s.label, s.url)) for s in c.sites]
    if f.watchlist_handles:
        comp.append(("发过的监控号：", "、".join(f.watchlist_handles)))
    if c.judgment:
        comp.append(("饱和判断：", c.judgment))
    doc.add(Bullets(comp) if comp else Para("没有记录竞争信息。"))

    doc.add(Heading(4, "怎么做"))
    h = j.howto
    if h.play:
        doc.add(Para("模板玩法", muted=True), Bullets([(f"{i}. ", s) for i, s in enumerate(h.play, 1)]))
    for label, text in (("用户输入", h.user_input), ("AI 工具", h.tools), ("BGM", h.bgm)):
        if text:
            doc.add(Bullets([(label + "：", text)]))
    if h.prompt:
        doc.add(Para("提示词（建议）", muted=True), Code(h.prompt))
    if h.negative_prompt:
        doc.add(Para("Negative prompt（建议）", muted=True), Code(h.negative_prompt))
    if h.caption or h.hashtags:
        doc.add(Bullets([(k, v) for k, v in (("标题：", h.caption), ("标签：", h.hashtags)) if v]))

    doc.add(Heading(4, "风险"))
    doc.add(Bullets([(None, r) for r in j.risks]) if j.risks else Para("未单独列出额外风险。"))


def _audience_items(m: PackMeme) -> list:
    groups: dict[tuple, list] = {}
    for a in m.facts.audience:
        groups.setdefault((a.hashtag, a.region, a.period, a.dimension, a.unit), []).append(a)
    items = []
    for (tag, region, period, dim, unit), rows in groups.items():
        dim_zh = {"age": "年龄", "country": "地区", "interest": "兴趣"}[dim]
        unit_zh = "%" if unit == "pct" else "（人气指数，不是占比）"
        body = "，".join(f"{a.bucket} {a.value:g}{'%' if unit == 'pct' else ''}" for a in rows[:6])
        items.append((f"#{tag} · {region} {period} 日 · {dim_zh}：", body + ("" if unit == "pct" else unit_zh) + "【第三方读数】"))
    return items
