# -*- coding: utf-8 -*-
"""Document assembly: ranking table + per-meme seven-block sections."""
from __future__ import annotations

from pathlib import Path

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, Cm, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from reportlib.cc_lib import row_by_tag, fmt_count, presence_table
from reportlib.docx_theme import (
    NAVY, TEAL, CORAL, INK, MUTED, WHITE, ACCENT_BG, WARN_BG, ALT_BG,
    init_document, add_header_footer, p, add_hyperlink, add_internal_hyperlink,
    add_bookmark, add_table, add_picture_fit, prevent_row_split, set_run_font,
    shade_cell, set_cell_text,
)
from reportlib.remix_lib import canonical_meme, pct, stats_for, MIN_N

VERDICT_FILL = {"做": "D5F5E3", "观望": "FCF3CF", "不做": "FADBD8"}
SUBS = ["热度", "趋势", "分享率", "竞争", "窗口"]


def bookmark_for(meme: dict) -> str:
    return "meme_" + meme["id"]


def display_name(meme: dict) -> str:
    zh = meme.get("name_zh") or ""
    name = meme["name"]
    if zh and zh not in name:
        return f"{name}（{zh}）"
    return name


def table_name(meme: dict) -> str:
    tag = meme.get("source_tag") or ""
    base = display_name(meme)
    return f"{base} {tag}".strip()


def _bullet(doc, text, bold_prefix=None, size=11):
    para = doc.add_paragraph(style="List Bullet")
    para.paragraph_format.space_after = Pt(3)
    para.paragraph_format.space_before = Pt(0)
    if bold_prefix:
        r = para.add_run(bold_prefix)
        set_run_font(r, size, True, NAVY)
        r = para.add_run(text)
        set_run_font(r, size, False, INK)
    else:
        r = para.add_run(text)
        set_run_font(r, size, False, INK)
    return para


def _caption(doc, text):
    p(doc, text, size=9, color=MUTED, space_before=0, space_after=10, italic=True)


def _link_line(doc, label, url, size=10):
    para = doc.add_paragraph(style="List Bullet")
    para.paragraph_format.space_after = Pt(2)
    para.paragraph_format.space_before = Pt(0)
    if url:
        add_hyperlink(para, label, url, size=size)
    else:
        r = para.add_run(label)
        set_run_font(r, size, False, INK)
    return para


def _code_block(doc, text):
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(2)
    para.paragraph_format.space_after = Pt(8)
    para.paragraph_format.left_indent = Cm(0.3)
    run = para.add_run(text)
    set_run_font(run, 9, False, INK)
    return para


def _score_cell(scores: dict) -> str:
    total = scores.get("total", 0)
    parts = " ".join(f"{k[:1]}{scores.get(k, 0)}" for k in SUBS)
    return f"{total}（{parts}）"


def _days_short(meme):
    return meme.get("days_hot_short") or (
        f"{meme['days_hot']} 天" if meme.get("days_hot") is not None else (meme.get("days_hot_label") or "—")
    )


def _peak_short(meme):
    return meme.get("peak_status_short") or (meme.get("peak_status") or "—")


def build_ranking_table(doc, memes):
    headers = ["排名", "梗", "综合评分", "结论", "窗口期", "已火天数", "高峰状态"]
    table = doc.add_table(rows=1 + len(memes), cols=7)
    table.style = "Table Grid"
    table.autofit = True
    widths = [1.2, 4.2, 3.2, 1.4, 2.2, 2.4, 2.6]
    for i, h in enumerate(headers):
        set_cell_text(table.cell(0, i), h, bold=True, size=8, color=WHITE, fill="1B3A4B", align="center")
    for i, meme in enumerate(memes):
        fill = "FFFFFF" if i % 2 == 0 else ALT_BG
        set_cell_text(table.cell(i + 1, 0), str(i + 1), size=8, fill=fill, align="center")
        cell = table.cell(i + 1, 1)
        shade_cell(cell, fill)
        cell.text = ""
        para = cell.paragraphs[0]
        para.paragraph_format.space_before = Pt(2)
        para.paragraph_format.space_after = Pt(2)
        add_internal_hyperlink(para, table_name(meme), bookmark_for(meme), size=8)
        set_cell_text(table.cell(i + 1, 2), _score_cell(meme["scores"]), size=7, fill=fill)
        vfill = VERDICT_FILL.get(meme["verdict"], fill)
        set_cell_text(table.cell(i + 1, 3), meme["verdict"], bold=True, size=8, fill=vfill, align="center")
        set_cell_text(table.cell(i + 1, 4), meme.get("window") or "—", size=8, fill=fill)
        set_cell_text(table.cell(i + 1, 5), _days_short(meme), size=8, fill=fill)
        set_cell_text(table.cell(i + 1, 6), _peak_short(meme), size=8, fill=fill)
    for row in table.rows:
        for idx, w in enumerate(widths):
            row.cells[idx].width = Cm(w)
    prevent_row_split(table)
    return table


def _kv_table(doc, rows, verdict=None):
    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    banner = VERDICT_FILL.get(verdict, ACCENT_BG)
    for i, (k, v) in enumerate(rows):
        fill = banner if i == 0 else ("FFFFFF" if i % 2 == 1 else "F7F9F9")
        set_cell_text(table.cell(i, 0), k, bold=True, size=9, color=NAVY, fill=fill)
        set_cell_text(table.cell(i, 1), v, size=9, fill=fill)
        table.cell(i, 0).width = Cm(3.6)
        table.cell(i, 1).width = Cm(14.2)
    prevent_row_split(table)
    return table


def _write_conclusion(doc, meme):
    doc.add_heading("结论卡", level=3)
    s = meme["scores"]
    score_line = (
        f"{s.get('total', 0)}/100　"
        + "　".join(f"{k} {s.get(k, 0)}/20" for k in SUBS)
    )
    rows = [
        ("做不做", meme["verdict"]),
        ("综合评分", score_line),
        ("热度 / 趋势 / 分享率 / 竞争 / 窗口",
         "　".join(f"{k} {s.get(k, 0)}" for k in SUBS)
         + "（等权，各 20 分）"),
        ("窗口期", meme.get("window") or "—"),
        ("起火日期", meme.get("ignite_date") or "未核实"),
        ("已火天数", str(meme.get("days_hot_label") or meme.get("days_hot") or "未核实")),
        ("是否仍在高峰", meme.get("peak_status") or "数据不足，不判断"),
        ("回测", meme.get("backtest_line") or "D+3 回测要到 11/13 才有首批对/错判断。在此之前记为数据不足。"),
        ("一句理由", meme.get("reason") or ""),
    ]
    notes = meme.get("score_notes") or {}
    if notes:
        detail = "；".join(f"{k}：{notes[k]}" for k in SUBS if notes.get(k))
        if detail:
            rows.append(("评分依据", detail))
    if meme.get("verdict_change"):
        delta = meme.get("score_delta")
        move = meme["verdict_change"]
        if delta is not None:
            move = f"{move}；综合评分相对 v5 {delta:+d}"
        rows.append(("相对 v5", move))
    _kv_table(doc, rows, verdict=meme.get("verdict"))
    p(doc, "", size=6, space_after=6)


def _write_what(doc, meme, remix_summary):
    doc.add_heading("是什么 + 链接", level=3)
    if meme.get("what"):
        p(doc, meme["what"], size=11, space_after=6)
    if meme.get("origin"):
        _bullet(doc, meme["origin"], bold_prefix="出处：")
    for item in meme.get("originals") or []:
        _link_line(doc, item.get("label") or item.get("url"), item.get("url"))
    extras = list(meme.get("examples") or [])
    # top remixes as extra examples
    key = meme.get("remix_key") or meme.get("name")
    plats = remix_summary.get(canonical_meme(key) or key) or {}
    vids = []
    for st in plats.values():
        vids.extend(st.videos)
    vids = sorted(vids, key=lambda v: -v.views)
    seen = {item.get("url") for item in (meme.get("originals") or [])}
    added = 0
    for v in vids:
        if not v.link or v.link in seen:
            continue
        extras.append({
            "label": f"示例二创 @{v.creator} · {v.platform} · {fmt_count(v.views)} 播放",
            "url": v.link,
        })
        seen.add(v.link)
        added += 1
        if added >= 5:
            break
    for item in extras:
        _link_line(doc, item.get("label") or item.get("url"), item.get("url"))
    for item in meme.get("trackers") or []:
        url = item.get("url") if isinstance(item, dict) else item
        label = item.get("label") if isinstance(item, dict) else ("追踪页 " + url.replace("https://", ""))
        _link_line(doc, label, url)
    if meme.get("tag_url"):
        _link_line(doc, "话题页 " + meme["tag_url"].replace("https://", ""), meme["tag_url"])


def _cc_rows(analysis, tags):
    if not analysis:
        return []
    rows = getattr(analysis, "rows", None) or ((analysis.d7 or []) + (analysis.d30 or []))
    return presence_table(rows, tags)



def _write_audience(doc, meme):
    rows = meme.get("cc_audience") or []
    if not rows:
        return
    p(doc, "受众（Creative Center 详情页）", size=11, bold=True, color=NAVY, space_before=6, space_after=3)
    for aud in rows:
        tag = aud.get("hashtag") or ""
        loc = f"{aud.get('region') or ''} {aud.get('period_days') or ''}日".strip()
        bits = []
        age = aud.get("age") or []
        if age:
            bits.append("年龄 " + "，".join(f"{a.get('bucket')} {a.get('pct')}%" for a in age) + "【第三方读数】")
        countries = aud.get("countries") or []
        if countries:
            metric = aud.get("countries_metric") or "popularity index (not %)"
            parts = []
            for c in countries[:5]:
                parts.append(f"{c.get('country')} {c.get('pct_or_rank')}")
            bits.append("地区人气指数（不是占比，" + metric + "）" + "；".join(parts))
        posts = aud.get("posts") or ""
        views = aud.get("views") or ""
        head = f"{tag} · {loc}"
        if posts or views:
            head += f"（窗口合计 {posts or '?'} 帖 / {views or '?'} 播放）"
        _bullet(doc, "。".join(bits) if bits else "该页未展示年龄或地区。", bold_prefix=head + "：")
    _caption(doc, "年龄是百分比；国家/地区是 popularity index，不是占比。详情页未展示兴趣、相关话题和创作者。")


def _write_heat(doc, meme, heat_map, charts, cc_analysis, cc_trends):
    doc.add_heading("热度曲线", level=3)
    _bullet(doc, meme.get("ignite_date") or "未核实到单一起火日", bold_prefix="起火日期：")
    _bullet(doc, str(meme.get("days_hot_label") or meme.get("days_hot") or "未核实"), bold_prefix="已火天数：")
    _bullet(doc, meme.get("peak_status") or "数据不足，不判断是否在高峰", bold_prefix="是否仍在高峰：")
    if meme.get("heat_position"):
        _bullet(doc, meme["heat_position"], bold_prefix="当前热度位置：")
    if meme.get("heat_sources"):
        _bullet(doc, "；".join(meme["heat_sources"]), bold_prefix="曲线来源：")
    if meme.get("heat_gaps"):
        _bullet(doc, meme["heat_gaps"], bold_prefix="缺口：")

    meme_heats = (charts or {}).get("meme_heats") or {}
    key = meme.get("remix_key") or meme.get("name")
    chart_path = meme_heats.get(key) or meme_heats.get(meme.get("name"))
    if chart_path:
        add_picture_fit(doc, chart_path, width_cm=16.8)
        _caption(doc, f"图　{display_name(meme)} 热度。上：近 7–11 日 X / ViralRemix（缺口不连、不补点；空心点为未满日或当日快照）。下：高播二创样本发布日与累计播放（不是全站日产量）。")

    cc_charts = (charts or {}).get("cc_trends") or {}
    drawn = []
    for tag in meme.get("cc_hashtags") or []:
        slug = tag.lstrip("#").lower()
        path = cc_charts.get(slug)
        if path:
            add_picture_fit(doc, path, width_cm=16.8)
            tr = (cc_trends or {}).get(slug)
            extra = ""
            if tr and tr.position:
                extra = " " + tr.position
            _caption(doc, f"图　#{slug} Creative Center 人气指数（7 日与 30 日各自归一化到 0–100，不能横比）。{extra}")
            drawn.append(slug)
        elif (cc_trends or {}).get(slug) and not (cc_trends[slug].has_series()):
            pass
    cc_rows = _cc_rows(cc_analysis, meme.get("cc_hashtags"))
    if cc_rows:
        tbl = add_table(doc, ["话题", "地区", "近 7 日（排名 · 帖/播）", "近 30 日（排名 · 帖/播）", "7日vs30日"],
                        cc_rows, [3.0, 1.6, 4.6, 4.6, 2.0])
        prevent_row_split(tbl)
        _caption(doc, "表　Creative Center 8 区 News & Entertainment 榜读数【第三方读数】。NL 页会跳到美国，没有独立荷兰榜。rank_change 为空，所以「NEW_7D / FADE_30D / SUSTAIN」只是同一地区 7 日榜 vs 30 日榜是否出现的代理，不是官方升降标。曲线止于 11/7，不是报告日。")
    _write_audience(doc, meme)


def _remix_table(doc, videos):
    headers = ["平台", "创作者 / 视频", "日期", "播放", "赞", "分享", "分享率", "AI"]
    table = doc.add_table(rows=1 + len(videos), cols=len(headers))
    table.style = "Table Grid"
    widths = [2.0, 4.2, 2.2, 2.0, 2.0, 1.8, 1.6, 1.2]
    for i, h in enumerate(headers):
        set_cell_text(table.cell(0, i), h, bold=True, size=8, color=WHITE, fill="1B3A4B", align="center")
    for i, v in enumerate(videos):
        fill = "FFFFFF" if i % 2 == 0 else ALT_BG
        creator = v.creator or "打开视频"
        if creator != "打开视频" and not creator.startswith("@"):
            creator = "@" + creator
        if len(creator) > 22:
            creator = creator[:21] + "…"
        vals = [
            v.platform,
            creator,
            v.date or "—",
            fmt_count(v.views),
            fmt_count(v.likes),
            fmt_count(v.shares),
            pct(v.share_rate),
            v.is_ai or "—",
        ]
        for c_i, val in enumerate(vals):
            if c_i == 1:
                cell = table.cell(i + 1, c_i)
                shade_cell(cell, fill)
                cell.text = ""
                para = cell.paragraphs[0]
                para.paragraph_format.space_before = Pt(2)
                para.paragraph_format.space_after = Pt(2)
                if v.link:
                    add_hyperlink(para, val, v.link, size=8)
                else:
                    run = para.add_run(val)
                    set_run_font(run, 8, False, INK)
            else:
                set_cell_text(table.cell(i + 1, c_i), val, size=8, fill=fill, align="center")
    for row in table.rows:
        for idx, w in enumerate(widths):
            row.cells[idx].width = Cm(w)
    prevent_row_split(table)


def _write_share(doc, meme, remix_summary):
    doc.add_heading("二创分享率", level=3)
    key = meme.get("remix_key") or meme.get("name")
    plats = remix_summary.get(canonical_meme(key) or key) or {}
    if not plats:
        p(doc, meme.get("share_read") or "没有读到足够的高播二创样本，不猜测分享率。评分里这一项按保守分处理。",
          size=11)
        if meme.get("tag_url"):
            _link_line(doc, "可在话题页查看视频 tiktok.com/tag/" + meme.get("id", ""), meme["tag_url"])
        return
    vids = []
    for plat, st in plats.items():
        prefix = "TikTok" if plat.lower() == "tiktok" else plat
        _bullet(doc, st.summary_zh() + "。" + st.verdict
                + ("。X 转发/曝光不可与 TikTok 分享/播放横比。" if plat == "X" else ""),
                bold_prefix=f"{prefix}：")
        vids.extend(st.videos)
    vids = sorted(vids, key=lambda v: -v.views)
    if vids:
        _remix_table(doc, vids)
        _caption(doc, "上表合并各平台、按播放/曝光排序的高播二创（已排除原视频）。创作者名为可点击链接。数字【已核实】。")
    if meme.get("share_read"):
        p(doc, meme["share_read"], size=11, space_before=4)


def _write_competition(doc, meme):
    doc.add_heading("竞争与模板", level=3)
    comp = meme.get("competition") or {}
    if comp.get("capcut"):
        _bullet(doc, comp["capcut"], bold_prefix="CapCut：")
    if comp.get("capcut_url"):
        _link_line(doc, "CapCut 模板页 " + comp["capcut_url"].replace("https://", ""), comp["capcut_url"])
    for site in comp.get("sites") or []:
        label = site.get("name") or site.get("url")
        _link_line(doc, label, site.get("url"))
    if comp.get("judgment"):
        _bullet(doc, comp["judgment"], bold_prefix="饱和判断：")


def _write_howto(doc, meme):
    doc.add_heading("怎么做", level=3)
    howto = meme.get("howto") or {}
    if meme.get("verdict") in {"观望", "不做"} or howto.get("framed"):
        p(doc, "如果要做，可以按下面的建议开工（本段为建议，不是已上线产品说明）。",
          size=10, color=MUTED, italic=True, space_after=6)
    else:
        p(doc, "下面是可以直接开工的建议（提示词为建议稿，可按模型再调）。",
          size=10, color=MUTED, italic=True, space_after=6)
    play = howto.get("play") or []
    if play:
        p(doc, "模板玩法", size=11, bold=True, color=NAVY, space_before=4, space_after=3)
        for i, step in enumerate(play, 1):
            _bullet(doc, step, bold_prefix=f"{i}. ")
    if howto.get("user_input"):
        p(doc, "用户输入", size=11, bold=True, color=NAVY, space_before=6, space_after=3)
        p(doc, howto["user_input"], size=11)
    if howto.get("tools"):
        p(doc, "AI 工具", size=11, bold=True, color=NAVY, space_before=6, space_after=3)
        p(doc, howto["tools"], size=11)
    if howto.get("prompt"):
        p(doc, "提示词（建议）", size=11, bold=True, color=NAVY, space_before=6, space_after=3)
        _code_block(doc, howto["prompt"])
    if howto.get("negative_prompt"):
        p(doc, "Negative prompt（建议）", size=11, bold=True, color=NAVY, space_before=2, space_after=3)
        _code_block(doc, howto["negative_prompt"])
    if howto.get("bgm"):
        p(doc, "BGM", size=11, bold=True, color=NAVY, space_before=2, space_after=3)
        p(doc, howto["bgm"], size=11)
    if howto.get("caption") or howto.get("hashtags"):
        p(doc, "标题与标签（建议）", size=11, bold=True, color=NAVY, space_before=6, space_after=3)
        if howto.get("caption"):
            _bullet(doc, howto["caption"], bold_prefix="标题：")
        if howto.get("hashtags"):
            _bullet(doc, howto["hashtags"], bold_prefix="标签：")


def _write_risks(doc, meme):
    doc.add_heading("风险", level=3)
    risks = meme.get("risks") or []
    if not risks:
        p(doc, "未单独列出额外风险。", size=11)
        return
    for r in risks:
        _bullet(doc, r)


def write_meme_section(doc, meme, idx_label, remix_summary, heat_map, charts, cc_analysis, cc_trends):
    heading = doc.add_heading(f"{idx_label}  {display_name(meme)}", level=2)
    add_bookmark(heading, bookmark_for(meme))
    _write_conclusion(doc, meme)
    _write_what(doc, meme, remix_summary)
    _write_heat(doc, meme, heat_map, charts, cc_analysis, cc_trends)
    _write_share(doc, meme, remix_summary)
    _write_competition(doc, meme)
    _write_howto(doc, meme)
    _write_risks(doc, meme)



def _write_backtest_block(doc, pack, backtest):
    doc.add_heading("回测", level=2)
    meta = pack.get("backtest") or {}
    bt = backtest or {}
    summary = bt.get("summary_zh") or meta.get("note_zh") or ""
    rule = meta.get("rule_zh") or bt.get("rule_zh") or ""
    first = meta.get("first_judgment_date") or "2026-11-13"
    if rule:
        p(doc, "规则：" + rule, size=10, space_after=4)
    p(doc, summary or f"首批对/错判断要到 {first} 才出现。在此之前，「做」的回测结果都是数据不足。",
      size=11, space_after=6)
    p(doc, f"今天是新流程试跑的报告日 D（2026-11-10）。D+3 是 {first}。现在不能用回测结果修正今天的名单。",
      size=10, color=MUTED, space_after=8)


def _write_changes_vs_v5(doc, pack):
    rows = pack.get("changes_vs_v5") or []
    if not rows:
        return
    doc.add_heading("相对 v5 的主要变动", level=2)
    p(doc, "同一天的 v5 是上一版结构试跑。下面只列出分数或结论有变化的梗，以及本次新进的话题。五项评分都按最新 8 区榜、重抓曲线和 11/10 热度重打。",
      size=10, color=MUTED, space_after=6)
    body = []
    for r in rows:
        delta = r.get("delta")
        changed = r.get("verdict_change") not in {"仍为做", "仍为观望", "仍为不做"} or (delta not in (None, 0))
        if not changed:
            continue
        if r.get("verdict_change") == "新进":
            score = f"{r.get('v6_total')}"
            prev = "—"
        else:
            score = f"{r.get('v5_total')}→{r.get('v6_total')}" + (f"（{delta:+d}）" if delta is not None else "")
            prev = r.get("v5_verdict") or "—"
        body.append([r.get("name") or "", prev, r.get("v6_verdict") or "", score, r.get("verdict_change") or ""])
    if body:
        tbl = add_table(doc, ["梗", "v5 结论", "v6 结论", "综合评分", "变动"], body, [4.4, 2.2, 2.2, 3.6, 3.4])
        prevent_row_split(tbl)
        _caption(doc, "表　相对 11/10 v5 的分数和结论变动。未列出的梗五项分数与结论都没有变。")


def build_docx(pack, remix_summary, heat_map, cc_analysis, cc_trends, charts, out_path, report_date, backtest=None):
    doc = init_document()
    version = pack.get("version") or "v6"
    title_note = pack.get("title_note") or "11/10 v6（新流程试跑）"
    add_header_footer(
        doc,
        f"AI 视频梗日报｜{report_date}　{title_note}",
        f"{version}　按综合评分决定今天做哪个模板　香港时间",
    )
    t = doc.add_paragraph()
    t.paragraph_format.space_after = Pt(2)
    r = t.add_run("AI 视频梗日报")
    set_run_font(r, 26, True, NAVY)
    p(doc, f"{report_date}（香港时间）　·　{title_note}　·　只回答一件事：今天该为哪个梗做 AI 模板",
      size=12, color=TEAL, space_after=8)
    p(doc,
      "这份报告是 11/10 新流程的试跑：8 区 Creative Center 榜、详情页曲线和受众、回测口径都按新约定写进来。"
      "按综合评分从高到低把每个梗写清楚。总排名表可以点进对应章节。"
      "观望和不做的梗也写完整怎么做，方便以后回看，但结论卡片上已经标明不要今天排期。",
      size=10, color=MUTED, space_after=12)

    memes = list(pack["memes"])
    ranked = sorted(memes, key=lambda m: (-int(m["scores"]["total"]), m["name"]))
    main = [m for m in ranked if m.get("part") != "early"]
    early = [m for m in ranked if m.get("part") == "early"]

    doc.add_heading("一、总排名", level=1)
    build_ranking_table(doc, ranked)
    p(doc,
      "【已核实】＝本报告从平台公开统计亲自读到；【第三方读数】＝ViralRemix / Turnly / Creative Center / Remake the Trend 等追踪站；"
      "【估算】＝追踪站累计估计。热度数字口径不同，不能把 X 日发帖、ViralRemix 日新视频和 Creative Center 播放直接横比。",
      size=9, color=MUTED, space_before=8, space_after=6)
    _write_backtest_block(doc, pack, backtest)
    _write_changes_vs_v5(doc, pack)
    rubric = pack.get("rubric") or {}
    if rubric:
        p(doc, "综合评分口径（五维等权，各 0–20 分，合计 100 分）", size=11, bold=True, color=NAVY, space_before=4)
        for key in SUBS + ["裁决"]:
            if rubric.get(key):
                _bullet(doc, rubric[key], bold_prefix=f"{key}：", size=10)
        p(doc, "缺数据的维度按保守分，不靠猜测抬分。", size=9, color=MUTED, space_after=10)

    doc.add_heading("二、逐个梗详解", level=1)
    p(doc, "按综合评分从高到低。每个梗七块结构相同：结论卡 → 是什么 + 链接 → 热度曲线 → 二创分享率 → 竞争与模板 → 怎么做 → 风险。",
      size=10, color=MUTED)
    for i, meme in enumerate(main, 1):
        write_meme_section(doc, meme, f"2.{i}", remix_summary, heat_map, charts, cc_analysis, cc_trends)

    doc.add_heading("三、早期信号", level=1)
    p(doc, "还没稳定进入主榜、但日增速已经很高或属于回潮的梗。同样打分，并出现在上面的总排名表里。适合轻量试水，不要单独压主研发。",
      size=10, color=MUTED)
    if not early:
        p(doc, "今日没有单独列出的早期信号。", size=11)
    for i, meme in enumerate(early, 1):
        write_meme_section(doc, meme, f"3.{i}", remix_summary, heat_map, charts, cc_analysis, cc_trends)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return str(out)
