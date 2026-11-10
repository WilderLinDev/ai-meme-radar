#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_daily_report.py
=====================
Regenerate the visual AI-video-meme daily report (charts + .docx).

Superseded by scripts/build_report.py. Kept so the older four-part
document can still be regenerated. Outputs use the same flat month folder.

Typical run for 2026-11-10
--------------------------
  python legacy/build_daily_report.py \\
      --date 2026-11-10 \\
      --md reports/2026-11/2026-11-10-daily-report.md \\
      --cc-csv reports/2026-11/2026-11-10-cc-top100-us.csv \\
      --remix-csv reports/2026-11/2026-11-10-remix-stats.csv \\
      --heat-json reports/2026-11/2026-11-10-heat.json \\
      --cc-trends-csv reports/2026-11/2026-11-10-cc-hashtag-trends.csv \\
      --out-docx reports/2026-11/2026-11-10-daily-report-legacy.docx \\
      --chart-dir reports/2026-11 \\
      --font assets/fonts/NotoSansSC-Regular.otf

Inputs
------
--md PATH           Daily digest markdown in the fixed format used by this
                    series (title with YYYY-MM-DD, ranking table, ### N｜name
                    entries, 往期回查, 早期信号). Numbers and 【已核实】/
                    【第三方读数】/【估算】 tags are copied, never invented.
--cc-csv PATH       Creative Center export with columns
                    period_days,rank,hashtag,posts,views,industry
                    (posts/views like 87.6K or 2.2B). UTF-8 with optional BOM.
--prev-cc-csv PATH  Optional previous day's CC CSV. When present, the script
                    computes rank change (prev_rank - today_rank) for 7d and
                    30d. The Creative Center page itself does not show rank
                    change; day 1 therefore has no day-over-day comparison.
--tag-notes PATH    Optional JSON overlay for researched hashtag blurbs and
                    recommendation cards. Missing tags are described from
                    data signals only (no invented origin stories).
--remix-csv PATH    Optional remix-video stats CSV (one row per 二创 video,
                    originals already excluded). Required columns: meme, link,
                    platform, creator, date, views, likes, shares, comments,
                    saves, is_AI. Optional: in_top_sample (yes/no; default yes),
                    verified, source, notes. The script computes per-meme
                    median and view-weighted share rate (shares/views), like
                    rate and shares/likes, separately for TikTok and X. A
                    platform group with n < 5 is labeled 样本不足. It also
                    builds the share-rate bar chart and the heat-vs-share
                    opportunity scatter, and inserts a compact share-rate
                    table into each meme card.
--heat-json PATH    Optional heat time series JSON (or pass --heat-csv).
                    JSON shape: {memes: {Name: {series: [{date,metric,value,source,complete}],
                    position, x_query, sources}}}. CSV alternative columns:
                    meme,date,metric,value,source[,complete]. complete=false marks
                    a partial day or same-day snapshot: it may be drawn as an
                    open marker but is never used for peak / 回落 math, and
                    missing dates stay as gaps (no interpolation). Typical
                    metrics: x_posts, viralremix_new_videos, remix_sample_posts,
                    remix_sample_views. The script draws a 7–11 day panel
                    (X + ViralRemix) and a longer remix-sample panel per meme.
--heat-csv PATH     Same data as --heat-json, CSV form.
--cc-trends-csv PATH
                    Optional Creative Center hashtag-detail trend export.
                    Columns: hashtag,period_days,date,value,metric,total_posts,
                    total_views,detail_url,status,related_video_links. Rows with
                    no date/value or status=not found are ignored. Detail pages
                    exist only for hashtags currently in the Top 100
                    (/creative/creativeCenter/trends/hashtag/<id>?region=US&period=7|30);
                    there is no search box. Values are a relative popularity
                    index 0-100, independently normalized inside each window,
                    so a 7-day 100 and a 30-day 100 are not the same volume.
                    Zero values are drawn as hollow markers and not connected
                    through. The builder draws a dual-panel 7d+30d chart and
                    states current position (刚起步/上升中/接近峰值/峰值/
                    回落 x% from peak) in section 4.3.
--date YYYY-MM-DD   Report date (default: parsed from the markdown title).
--out-docx PATH     Output Word file.
--chart-dir PATH    Directory for PNG charts (~1600px wide).
--font PATH         CJK font file used by matplotlib and declared as the
                    East-Asian font in the docx.

What is automatic vs written
----------------------------
Automatic from the CSV: bucket classification, posts/views totals, views-per-
post, 新冒头 (in 7d not 30d), 持续热 (in both), 退潮 (in 30d not 7d), Top 20
charts, scatter, lifecycle counts, rank change when a previous CSV exists.
Automatic from the markdown: ranking table, per-meme bullets, 往期, 早期信号,
X daily endpoints if a "每日 M/D n → M/D n" line is present, core-metric bars.
Automatic from --remix-csv: per-meme share-rate tables, median / weighted
rates, TikTok share-rate bar, heat-vs-share scatter. TikTok shares and X
reposts are never mixed.
Written / notes: 今日结论 picks and 做/观望/不做 (informed by heat + share
rate + CapCut saturation, not invented numbers), researched Creative Center
建议做 / 不建议做 that need outside context (IP, official campaigns, news).

v4 document outline
-------------------
0. Cover + one-line data caveat (share-rate definition; organized by meme, not platform)
1. 今日结论: 1-3 picks, 今日不做, overview table (includes 当前热度位置)
2. AI梗热度榜
   2.1 ranking table + heat chart
   2.2 trend + opportunity matrix (share-rate bar and heat vs share scatter,
       colored/marked by platform, not split into TikTok vs other-platform charts)
   2.3 per-meme cards, always in this order:
       基本信息+链接 (original + tracker + CapCut note + CC cross-ref, as hyperlinks)
       → 热度曲线(7日/30日)+当前位置
       → 二创传播质量 (one merged table with a platform column and clickable remix links;
         share rate still computed per platform inside the same card)
       → 玩法与工具 → 结论与做法
3. 早期信号 (also merged across platforms; heat panel when data exists)
4. TikTok Creative Center: 4.1 buckets, 4.2 lifecycle, 4.3 do, 4.4 don't
   (stays its own section as a source of new hashtags; mapped tags are
   cross-referenced inside the matching meme card)
5. 往期回查
6. 今日行动清单
Appendix: sources / definitions + full hashtag classification table
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths as P  # noqa: E402
P.prepare_reportlib()

from reportlib.cc_lib import (
    BUCKET_ORDER, analyze_cc, fmt_count, row_by_tag, signal_of,
)
from reportlib.charts import make_all_charts
from reportlib.md_parse import parse_digest
from reportlib.docx_theme import (
    NAVY, TEAL, CORAL, INK, MUTED, WHITE, ACCENT_BG, WARN_BG, ALT_BG,
    init_document, add_header_footer, p, add_runs, add_hyperlink,
    add_table, add_picture_fit, prevent_row_split, set_run_font, set_cell_text,
)
from reportlib.remix_lib import (
    NICK, load_remix_csv, summarize_remixes, tiktok_points,
)
from reportlib.docx_v3 import MEME_META
from reportlib.docx_v4 import build_docx_v4
from reportlib.heat_lib import load_heat
from reportlib.cc_trends import load_cc_trends
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# Researched blurbs for 2026-11-10 (and reusable if the same tags recur).
# Each entry is keyed by lowercase hashtag.
DEFAULT_TAG_NOTES = {
    "#godzillaminuszero": {
        "what": "东宝《哥斯拉 -0.0》（Godzilla Minus Zero），山崎贵执导，2026-11-03 日本上映。TikTok Spotlight 全球投稿活动 11/3–12/18，美日有 Search Hub。",
        "source": "https://prtimes.jp/main/html/rd/p/000001362.000030435.html",
        "source_label": "PR TIMES / TikTok × 东宝",
        "angle": "怪兽摧毁城市很适合 AI 视频，但是未授权使用哥斯拉形象有明确 IP 风险。官方活动在给带指定标签的投稿导流，不要做山寨官方模板。",
        "verdict": "不建议做",
    },
    "#transformers": {
        "what": "变形金刚粉丝二创、剪辑，以及关于迈克尔·贝可能回归执导新片的讨论。7 日榜帖量不低但单帖播放一般，更像大众参与而不是单条爆款。",
        "source": "https://toklytics.app/hashtag/transformers",
        "source_label": "Toklytics 标签页",
        "angle": "机器人变形是经典 AI 视觉，但角色与商标受版权保护。",
        "verdict": "不建议做",
    },
    "#lastchristmas": {
        "what": "Wham!（乔治·迈克尔）1984 年的圣诞单曲《Last Christmas》每年 11 月起在 TikTok 回潮，用来做情侣、遗憾、圣诞集市和怀旧拼接。它是今天两份榜单里几乎唯一的非政治「持续热」话题。",
        "source": "https://www.billboard.com/music/chart-beat/wham-last-christmas-number-1-tiktok-billboard-top-50-chart-1235867278/",
        "source_label": "Billboard（歌曲在 TikTok 榜单的历史表现）",
        "angle": "一张或两张情侣/家庭照片生成冬日圣诞短片，情绪是怀念和复合。不要在独立站点里内置 Wham! 原曲，让用户到 TikTok 自己贴热门音频。",
        "verdict": "建议做",
    },
    "#stickerbanner": {
        "what": "把一张宽图或循环视频切成 3/6/9 张方形贴纸，发到主页 Stickers 页拼成全景横幅。已有独立切图工具。",
        "source": "https://stickerbanner.org/",
        "source_label": "Sticker Banner 工具站",
        "angle": "这是主页装饰工具，不是 AI 视频梗。相邻生意已经有人在做，不必当作一键视频站的主线。",
        "verdict": "不建议做（视频站主线）",
    },
    "#coderot": {
        "what": "把失效滤镜或老游戏的「代码腐烂」演成伪恐怖。2026 年 10 月中下旬围绕 Despicable Me 4 滤镜爆开，口头禅是 “Yep, it's code rotted indeed”。",
        "source": "https://trendhaus.ai/tiktok-trends/code-rot",
        "source_label": "Trendhaus",
        "angle": "模拟故障 + 模拟恐怖的格式可以借鉴到冬日恐悚短片，但这个标签本身已不在 7 日榜，且绑着小黄人滤镜 IP。",
        "verdict": "不建议追标签",
    },
    "#youcanseeeverything": {
        "what": "Nathan Fielder 与 Lance Oppenheim 执导、A24 发行的伊丽莎白·霍姆斯纪录片，2026-10-16 北美上映。网上流行她那句死板的 “Why would I deceive you?” 对剪反应。",
        "source": "https://en.wikipedia.org/wiki/You_Can_See_Everything",
        "source_label": "Wikipedia",
        "angle": "反应梗和表情包，不是一键视频格式。单帖播放很高，属于头部内容驱动。",
        "verdict": "不建议做",
    },
    "#imsosorry": {
        "what": "幻灯片揭穿：先放出精修照片，再一页页道歉承认修图，最后甩出原图。2026 年 8 月出现，10 月万圣节版（童年服装揭穿）放量。",
        "source": "https://trending.knowyourmeme.com/editorials/guides/what-is-the-im-so-sorry-trend-the-meaning-of-the-viral-tiktok-memes-explained",
        "source_label": "Know Your Meme",
        "angle": "可以做成「精修图 + 原图」幻灯片模板，但万圣节红利已过，标签已不在 7 日榜，优先级低于舞类和圣诞。",
        "verdict": "低优先",
    },
    "#captainsaveaho": {
        "what": "Fresh X Reckless 的歌《Captain Save Uh Ho (Girl Where You Going)》（2022）带动的舞蹈和口头禅，2026 年 10 月又出现在 30 日榜。",
        "source": "https://www.distractify.com/p/girl-where-you-going-tiktok",
        "source_label": "Distractify",
        "angle": "真人舞蹈，不是照片生成视频；歌词也不适合品牌安全的模板站。",
        "verdict": "不建议做",
    },
    "#loozecannon": {
        "what": "底特律表演者 Glen Cannon 的网名。他用 AI 脸部滤镜在 TikTok Live 里扮演迈克尔·杰克逊即兴说唱，歌曲梗是 “Big Michael Michael”。",
        "source": "https://www.galvnews.com/news_reuters/nation/he-transformed-himself-into-michael-jackson-tiktok-went-wild/article_3e53321b-e7b4-525f-a943-ed2d34b07cd0.html",
        "source_label": "Reuters 转载",
        "angle": "演示了「AI 变脸直播人设」有市场，但迈克尔·杰克逊肖像权和形象权风险很高，不能做成一键变 MJ 的产品。",
        "verdict": "不建议做",
    },
    "#loozecannon1": {
        "what": "与 #loozecannon 同一人，其 TikTok 账号是 @loozecannon1。",
        "source": "https://www.vibesynced.com/blog/looze-cannon-michael-jackson-tiktok-live-ddg-lil-baby/",
        "source_label": "VibeSynced",
        "angle": "同上，肖像权风险。",
        "verdict": "不建议做",
    },
    "#damehombro": {
        "what": "西班牙文「把肩膀给我」。Bulin 47 与 Kevin Wai 2026-10-07 发行的 dembow，核心动作是跟着节拍抖肩。和日报里正在回落的 Bulin 47 AI 视频梗不是同一件事。",
        "source": "https://damehombro.co/dame-hombro-meaning/",
        "source_label": "Dame Hombro 词义说明",
        "angle": "简单抖肩可以做成照片生成舞蹈，但标签已不在 7 日榜，属于退潮；不必当新品主推。可继续观察它和已有 Bulin 追踪的关系。",
        "verdict": "观察，不主推",
    },
    "#halloweentransition": {
        "what": "万圣节变装过渡：先日常服装或局部特写，卡点切到完整角色造型。常见拖鞋低机位抬镜头、挥手、转圈等手法。",
        "source": "https://www.fastcompany.com/91633112/tiktok-has-a-new-halloween-obsession-and-its-not-about-what-people-are-wearing",
        "source_label": "Fast Company",
        "angle": "万圣节本身已结束。可复用的是「照片 A → 照片 B 的电影感过渡」，做成常青变身模板，不要再绑定万圣节标签。",
        "verdict": "借鉴格式，不追标签",
    },
    "#couplescostume": {
        "what": "情侣万圣节造型。30 日播放不低，但季节已过。",
        "source": "https://www.fastcompany.com/91633112/tiktok-has-a-new-halloween-obsession-and-its-not-about-what-people-are-wearing",
        "source_label": "Fast Company（变装大盘）",
        "angle": "情侣合照生成视频仍有价值，应换到圣诞/冬季场景，而不是继续做服装主题。",
        "verdict": "不追季节标签",
    },
    "#yorkshirewildlifepark": {
        "what": "2026 年 10 月英国约克郡野生动物园虎园致死事件，死者在拍摄时进入东北虎围栏。高播放来自新闻和现场视频，不是娱乐挑战。",
        "source": "https://www.bbc.co.uk/news/articles/c9146j15gnggo",
        "source_label": "BBC News",
        "angle": "真实死亡事件，绝不能做成娱乐或 AI 模板。",
        "verdict": "严禁做",
    },
    "#georgieandmandysfirstmarriage": {
        "what": "CBS 情景喜剧《Georgie & Mandy's First Marriage》（《小谢尔顿》衍生剧）的讨论和片段标签。",
        "source": "https://toklytics.app/hashtag/georgieandmandysfirstmarriage",
        "source_label": "Toklytics",
        "angle": "剧集切片，不是用户上传照片就能复用的格式，且涉及影视版权。",
        "verdict": "不建议做",
    },
    "#clayface": {
        "what": "DC 电影《Clayface》，美国 2026-10-23 上映，是一部偏恐怖的反派起源故事。黏土人面容变形天然像 AI 视频卖点。",
        "source": "https://www.dc.com/movies/clayface-2026",
        "source_label": "DC 官网",
        "angle": "不要做未授权的 Clayface / 蝙蝠侠宇宙角色生成。若做「人脸融化/黏土化」特效，必须完全避开官方角色名和外形。",
        "verdict": "不建议做（官方角色）",
    },
    "#visionquest": {
        "what": "漫威剧集《VisionQuest》，Disney+ 于 2026-10-14 开播，保罗·贝坦尼继续演幻视，本期终集安排在 11/10。",
        "source": "https://www.disneyplus.com/explore/articles/marvel-visionquest",
        "source_label": "Disney+",
        "angle": "超级英雄剧集物料，版权风险高，且终集过后热度会掉。",
        "verdict": "不建议做",
    },
    "#brandrisk": {
        "what": "Adin Ross 旗下的创作者搏击品牌 Brand Risk，打拳击 / MMA / 踢拳，标签下主要是赛事切片。行业标记也是 Sports & Outdoor。",
        "source": "https://reelshift.app/blog/brandrisk",
        "source_label": "Brand Risk 赛事说明",
        "angle": "单帖播放极高，是头部赛事内容，不是大众参与的照片模板。",
        "verdict": "不建议做",
    },
    "#acosh": {
        "what": "BookTok 缩写，指莎拉·J·马斯《A Court of Splintered Harmony》（《荆棘与玫瑰》系列第 6 部），2026-10-27 出版。",
        "source": "https://www.yahoo.com/entertainment/article/a-court-of-splintered-harmony-is-here--but-booktok-has-turned-reading-acotar-6-into-a-race-against-spoilers-160029861.html",
        "source_label": "Yahoo / BookTok 报道",
        "angle": "角色AI绘图或动态壁纸有需求，但人物与设定受版权保护，不适合做成未授权一键站。",
        "verdict": "不建议做",
    },
    "#nnn": {
        "what": "No Nut November，每年 11 月的成人禁欲网络梗。",
        "source": "https://en.wikipedia.org/wiki/No_Nut_November",
        "source_label": "Wikipedia",
        "angle": "热度不低，但内容政策风险高，品牌广告也接不住。",
        "verdict": "不建议做",
    },
    "#veteransday": {
        "what": "美国退伍军人节，2026 年是 11 月 11 日（本报告次日）。7 日榜新冒头，单帖播放偏低，说明开始出现大量普通用户投稿。",
        "source": "https://www.va.gov/opa/vetsday/",
        "source_label": "美国退伍军人事务部",
        "angle": "窗口只有 1–2 天。商业一键模板很容易显得功利，不作为产品重点。",
        "verdict": "不作为重点",
    },
    "#strangerthingsday": {
        "what": "《怪奇物语》日，通常是 11 月 6 日。今年这一天已过。",
        "source": "https://en.wikipedia.org/wiki/Stranger_Things",
        "source_label": "Wikipedia / Stranger Things（11 月 6 日是惯例节日）",
        "angle": "节日已过，且角色与世界是奈飞版权。",
        "verdict": "不建议做",
    },
    "#tiktokscaryhorrorcontest": {
        "what": "TikTok 万圣节前后的恐怖短片活动标签，30 日榜第 1 名，2.2B 播放。它已不在 7 日榜，说明活动期已过。",
        "source": "https://hiviolet.ai/signals/tiktok/hashtags/tiktokscaryhorrorcontest",
        "source_label": "Hi Violet 标签轨迹",
        "angle": "不要再追这个比赛标签。它证明「短恐悚」在 N&E 类目能做到十亿级播放，这个格式可以做成常青模板。",
        "verdict": "借鉴格式，不追标签",
    },
    "#tiktokthrillermysterycontest": {
        "what": "与恐怖比赛同期的悬疑/推理短片活动标签，30 日榜第 4，403.2M 播放，同样已离开 7 日榜。",
        "source": "https://hiviolet.ai/signals/tiktok/hashtags/tiktokscaryhorrorcontest",
        "source_label": "同类活动标签",
        "angle": "反转、未解之谜、第一视角探查很适合 AI 短片。做成「上传一张照片生成 15 秒悬疑短片」，不要使用官方比赛名。",
        "verdict": "借鉴格式，不追标签",
    },
    "#livecanbeeasy": {
        "what": "TikTok LIVE 创作者激励/任务标签，强调直播可以很容易开始。近 7 日高居第 2，但不在 30 日榜，是本周平台活动拉起来的。",
        "source": "https://www.tiktok.com/livefest",
        "source_label": "TikTok LIVE Fest",
        "angle": "平台发钱发任务，不是消费者想看的视频格式。",
        "verdict": "不建议做",
    },
    "#livemonetization": {
        "what": "分享直播变现经历的激励标签，和 #mylivejourney、#livefest2026 同一簇。",
        "source": "https://www.tiktok.com/livefest",
        "source_label": "TikTok LIVE Fest",
        "angle": "创作者运营内容，不是一键娱乐视频需求。",
        "verdict": "不建议做",
    },
    "#mylivejourney": {
        "what": "创作者讲述自己直播成长故事的官方激励标签。",
        "source": "https://www.tiktok.com/livefest",
        "source_label": "TikTok LIVE Fest",
        "angle": "同上。",
        "verdict": "不建议做",
    },
    "#livefest2026": {
        "what": "TikTok LIVE Fest 2026。公开信息称任务积分持续到 11/19，区域赛 11/20–12/15，全球决赛 12/17–21。7 日榜第 21，11.17 万帖 / 5.01 亿播放。",
        "source": "https://www.tiktok.com/livefest",
        "source_label": "TikTok LIVE Fest",
        "angle": "官方大型直播赛事，不是模板需求。",
        "verdict": "不建议做",
    },
}


def load_notes(path):
    notes = dict(DEFAULT_TAG_NOTES)
    if path:
        extra = json.loads(Path(path).read_text(encoding="utf-8"))
        notes.update(extra)
    return notes


def parse_core_metric(core: str):
    m = re.search(r"X 7 天\s*([\d,]+)", core)
    if m:
        return int(m.group(1).replace(",", "")), "X 7天发帖"
    m = re.search(r"ViralRemix\s*([\d.]+)K/天", core)
    if m:
        return float(m.group(1)) * 1000, "ViralRemix/天"
    m = re.search(r"Turnly\s*(\d+)", core)
    if m:
        return int(m.group(1)), "Turnly 创作者"
    m = re.search(r"原帖\s*([\d.]+)M", core)
    if m:
        return float(m.group(1)) * 1e6, "原帖播放"
    return None, None


def extract_x_daily(digest):
    series = {}
    pat = re.compile(
        r"每日\s*(\d+)/(\d+)\s*([\d,]+)\s*→\s*(\d+)/(\d+)\s*([\d,]+)"
    )
    for e in digest.entries:
        blob = " ".join(e.bullets)
        m = pat.search(blob)
        if not m:
            continue
        key = "Bicep Heart" if "bicep" in e.name.lower() else (
            "Malfoid" if "malfoid" in e.name.lower() else e.name.split()[0]
        )
        d1 = f"11/{int(m.group(2)):02d}" if m.group(1) == "11" else f"{m.group(1)}/{m.group(2)}"
        d2 = f"11/{int(m.group(5)):02d}" if m.group(4) == "11" else f"{m.group(4)}/{m.group(5)}"
        # keep readable labels
        lab1 = f"{m.group(1)}/{m.group(2)}"
        lab2 = f"{m.group(4)}/{m.group(5)}"
        series[key] = [
            (lab1, int(m.group(3).replace(",", ""))),
            (lab2, int(m.group(6).replace(",", ""))),
        ]
    return series


def matrix_from_digest(digest):
    items = []
    for e in digest.entries:
        text = " ".join(e.bullets) + " " + e.suggest + " " + e.name
        short = re.split(r"[（(]", e.name)[0].strip()
        nick_rules = [
            ("Shoulder Carry", "Shoulder Carry"),
            ("Can I Ride", "Can I Ride"),
            ("Ba Ba Ba", "Ba Ba Ba"),
            ("Bicep Heart", "Bicep Heart"),
            ("Flamingo", "Flamingo Float"),
            ("Grandpa", "切鱼梗"),
            ("Malfoid", "Malfoid"),
            ("Cat on Ultra", "Cat on Ultra Bee"),
        ]
        for key, nick in nick_rules:
            if key.lower() in e.name.lower():
                short = nick
                break
        if "⭐" in e.suggest or "最值得" in e.suggest:
            tag, heat, sat = "建议做", 8.2, 2.4
        elif "手绘" in text or "不是 AI" in text or "不是AI" in text:
            tag, heat, sat = "非AI视频", 8.0, 9.0
        elif "已做开" in text or "只能拼" in e.suggest:
            tag, heat, sat = "饱和", 6.0, 8.8
        elif "尽快" in e.suggest:
            tag, heat, sat = "建议做", 7.6, 2.0
        elif re.search(r"窗口约\s*2[–-]3", e.suggest):
            tag, heat, sat = "窗口将尽", 7.0, 7.0
        elif re.search(r"窗口约\s*3[–-]5", e.suggest):
            tag, heat, sat = "窗口将尽", 6.5, 6.0
        elif "新上榜" in text or "新上榜" in e.change:
            tag, heat, sat = "建议做", 5.0, 2.2
        elif "峰值" in text:
            tag, heat, sat = "峰值可做", 8.6, 5.0
        else:
            tag, heat, sat = "峰值可做", 6.0, 5.0
        items.append({"name": short[:18], "heat": heat, "sat": sat, "tag": tag})
    for i, line in enumerate(digest.early):
        name = line.split("（")[0].split(":")[0].split("：")[0]
        name = re.sub(r"https?://\S+", "", name).strip(" -|")
        early_nick = [
            ("Then I Walk In", "Then I Walk In"),
            ("Turning My Mom", "Mom Into Me"),
            ("Shaking Head", "宠物摇头"),
        ]
        for key, nick in early_nick:
            if key.lower() in name.lower() or key.lower() in line.lower():
                name = nick
                break
        sat = 4.4 if "回潮" in line or "makeviral" in line.lower() else 1.8 + i * 0.4
        items.append({"name": name[:18], "heat": 3.0 + i * 0.4, "sat": sat, "tag": "早期信号"})
    return items


def highlight_tags():
    return [
        "#lastchristmas", "#godzillaminuszero", "#transformers",
        "#veteransday", "#strangerthingsday", "#stickerbanner",
        "#coderot", "#youcanseeeverything", "#imsosorry",
        "#damehombro", "#halloweentransition", "#clayface",
        "#visionquest", "#tiktokscaryhorrorcontest",
        "#tiktokthrillermysterycontest", "#livefest2026",
        "#nnn", "#acosh", "#brandrisk", "#yorkshirewildlifepark",
        "#loozecannon", "#captainsaveaho",
    ]


def scatter_label_tags():
    return [
        "#lastchristmas", "#godzillaminuszero", "#transformers",
        "#veteransday", "#tiktokscaryhorrorcontest", "#stickerbanner",
        "#livefest2026", "#damehombro", "#coderot", "#nnn",
    ]


def shade_para(paragraph, hex_color):
    ppr = paragraph._p.get_or_add_pPr()
    for old in ppr.findall(qn("w:shd")):
        ppr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_color)
    spacing = ppr.find(qn("w:spacing"))
    if spacing is not None:
        spacing.addprevious(shd)
    else:
        ppr.insert(0, shd)


def callout(doc, title, body, fill="E8F6F3"):
    para = p(doc, "", space_after=2, space_before=4)
    run = para.add_run(title)
    set_run_font(run, 11, True, NAVY)
    shade_para(para, fill)
    para2 = p(doc, body, size=10, space_after=10)
    shade_para(para2, fill)
    return para2


def bullet(doc, text, bold_prefix=None, extra=None):
    para = doc.add_paragraph(style="List Bullet")
    para.paragraph_format.space_after = Pt(3)
    para.paragraph_format.space_before = Pt(0)
    if bold_prefix:
        r = para.add_run(bold_prefix)
        set_run_font(r, 11, True, NAVY)
        r = para.add_run(text)
        set_run_font(r, 11, False, INK)
    else:
        r = para.add_run(text)
        set_run_font(r, 11, False, INK)
    if extra:
        extra(para)
    return para


def add_sources_line(doc, urls):
    if not urls:
        return
    para = p(doc, "来源：", size=9, color=MUTED, space_after=8)
    para.clear()
    r = para.add_run("来源：")
    set_run_font(r, 9, False, MUTED)
    for i, url in enumerate(urls):
        if i:
            sep = para.add_run("  ·  ")
            set_run_font(sep, 9, False, MUTED)
        add_hyperlink(para, url.replace("https://", ""), url if url.startswith("http") else "https://" + url, size=9)


def data_pair(analysis, tag):
    r7 = row_by_tag(analysis.d7, tag)
    r30 = row_by_tag(analysis.d30, tag)
    bits = []
    if r7:
        bits.append(f"7日第{r7.rank}，{r7.posts_raw}帖 / {r7.views_raw}播放，单帖约 {fmt_count(r7.vpp)}")
    else:
        bits.append("不在7日榜")
    if r30:
        bits.append(f"30日第{r30.rank}，{r30.posts_raw}帖 / {r30.views_raw}播放，单帖约 {fmt_count(r30.vpp)}")
    else:
        bits.append("不在30日榜")
    sig = ""
    sample = r7 or r30
    if sample:
        sig = signal_of(sample, analysis)
    return "；".join(bits), sig


def build_docx(digest, analysis, charts, notes, out_path, report_date):
    doc = init_document()
    add_header_footer(
        doc,
        f"AI 视频梗日报｜{report_date}",
        "美国 · News & Entertainment　香港时间",
    )

    # Title
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.LEFT
    t.paragraph_format.space_after = Pt(2)
    r = t.add_run(f"AI 视频梗日报")
    set_run_font(r, 26, True, NAVY)
    sub = p(doc, f"{report_date}（香港时间）　·　深度分析版　·　含 TikTok Creative Center 美国 News & Entertainment",
            size=12, color=TEAL, space_after=8)

    if digest.caveat:
        note = p(doc, digest.caveat, size=9, color=MUTED, space_after=12)
        note.runs[0].italic = True

    # 今日要点
    doc.add_heading("今日要点", level=1)
    pol_views = analysis.bucket7.get("美国中期选举/政治", {}).get("views", 0)
    pol_share = 100 * pol_views / (analysis.totals7["views"] or 1)
    highlights = [
        ("今日首选 Shoulder Carry：",
         "音频已有 308,343 条视频，CapCut 模板 “Cause I'm The One” 只用了 5,397 次【第三方读数】。AI 版远未饱和，窗口约 5–7 天。"),
        ("增速最快 Can I Ride：",
         "ViralRemix 24.3K/天，▲89%【第三方读数】，尚未核实到 CapCut 主模板，应尽快上双人舞。"),
        ("圣诞窗口已经打开：",
         "Creative Center 两份榜里，非政治的「持续热」话题几乎只剩 #lastchristmas（7日第68，4.7K帖/27.8M；30日第65，6.3K帖/43.2M）。现在就该做情侣/怀旧冬日模板，不要内置 Wham! 原曲。"),
        ("新上榜 Cat on Ultra Bee：",
         "原帖 1.2M 播放【第三方读数】，玩法是宠物照片生成越野车翘头，窗口约 4–6 天。"),
        ("不要被 7 日榜骗去做政治或直播任务：",
         f"近 7 日播放的 {pol_share:.1f}% 来自美国中期选举/政治（约 {fmt_count(pol_views)}），再加 TikTok LIVE Fest 一类激励标签。那是新闻和平台任务，不是消费者一键视频需求。万圣节集群已从 7 日榜消失，属于退潮。"),
    ]
    for pref, rest in highlights:
        bullet(doc, rest, bold_prefix=pref)

    # 一、AI 梗
    doc.add_heading("一、AI 梗热度排行", level=1)
    p(doc,
      "下列三张图分别解决三件事：各梗自己的核心读数、Bicep Heart / Malfoid 的两端回落、以及「该不该做」的定性位置。不同颜色的柱子单位不同，不能横比长短。",
      size=10, color=MUTED)

    add_picture_fit(doc, charts["ai_heat"])
    add_picture_fit(doc, charts["x_daily"])
    add_picture_fit(doc, charts["matrix"])

    doc.add_heading("排行表", level=2)
    rank_rows = []
    for row in digest.ranking:
        rank_rows.append([str(row["rank"]), row["name"], row["change"], row["core"]])
    tbl = add_table(doc, ["排名", "梗", "变化 vs 11/9", "核心热度"], rank_rows, [1.6, 5.2, 3.6, 7.2])
    prevent_row_split(tbl)
    p(doc, "", space_after=4)

    for e in digest.entries:
        doc.add_heading(f"{e.rank}｜{e.name}", level=2)
        if e.core:
            para = p(doc, "", space_after=4)
            r = para.add_run("核心热度  ")
            set_run_font(r, 10, True, TEAL)
            r = para.add_run(e.core)
            set_run_font(r, 10, False, INK)
        if e.change:
            para = p(doc, "", space_after=4)
            r = para.add_run("相对昨日  ")
            set_run_font(r, 10, True, TEAL)
            r = para.add_run(e.change)
            set_run_font(r, 10, False, INK)
        urls = list(e.sources or [])
        for b in e.bullets:
            if b.startswith("跟拍建议"):
                continue
            found = re.findall(r"https?://\S+", b)
            for u in found:
                if u not in urls:
                    urls.append(u)
            if b.startswith("来源"):
                continue
            cleaned = re.sub(r"来源[：:]\s*https?://\S+", "", b)
            cleaned = re.sub(r"https?://\S+", "", cleaned).strip(" ；。; ")
            if cleaned:
                bullet(doc, cleaned)
        if e.suggest:
            callout(doc, "跟拍建议  ", e.suggest, fill="E8F6F3")
        add_sources_line(doc, urls)

    # 二、往期
    doc.add_heading("二、往期条目回查", level=1)
    for line in digest.revisit:
        bullet(doc, line)

    # 三、早期信号
    doc.add_heading("三、早期信号（刚冒头）", level=1)
    p(doc, "这三个还没进主榜，但第三方日增速已经很高，适合先做轻量模板、不要压主研发。", size=10, color=MUTED)
    for i, line in enumerate(digest.early, 1):
        urls = re.findall(r"https?://\S+", line)
        text = re.sub(r"https?://\S+", "", line).strip(" ｜|")
        bullet(doc, text, bold_prefix=f"{i}. ")
        add_sources_line(doc, urls)

    # 四、CC
    doc.add_heading("四、TikTok Creative Center 深度分析", level=1)
    p(doc,
      "口径：美国 · News & Entertainment 话题榜，近 7 日与近 30 日各 Top 100。今日是第一次接入，Creative Center 页面本身不显示排名升降，因此没有「比昨天上升几名」。下面的「新冒头 / 持续热 / 退潮」是用两份榜的交集和差集推出来的：只在 7 日榜 = 新冒头，两份都有 = 持续热，只在 30 日榜 = 退潮。",
      size=10)

    doc.add_heading("4.1 两份榜单在讲什么", level=2)
    p(doc,
      f"近 7 日 Top 100 合计约 {fmt_count(analysis.totals7['posts'])} 帖、{fmt_count(analysis.totals7['views'])} 播放。"
      f"近 30 日合计约 {fmt_count(analysis.totals30['posts'])} 帖、{fmt_count(analysis.totals30['views'])} 播放。"
      "7 日被中期选举和 LIVE 激励占据；30 日被万圣节及其比赛标签撑大。AI 视频梗几乎不会出现在这个行业分类里，所以这份榜单的价值是判断季节、官方活动和可挪用的格式，而不是直接给 AI 梗排名。",
      size=11)

    add_picture_fit(doc, charts["buckets"])

    bucket_rows = []
    for b in BUCKET_ORDER:
        a = analysis.bucket7.get(b, {"n": 0, "posts": 0, "views": 0})
        c = analysis.bucket30.get(b, {"n": 0, "posts": 0, "views": 0})
        t7p, t7v = analysis.totals7["posts"] or 1, analysis.totals7["views"] or 1
        t30p, t30v = analysis.totals30["posts"] or 1, analysis.totals30["views"] or 1
        bucket_rows.append([
            b,
            str(a["n"]),
            f"{fmt_count(a['posts'])}（{100*a['posts']/t7p:.1f}%）",
            f"{fmt_count(a['views'])}（{100*a['views']/t7v:.1f}%）",
            str(c["n"]),
            f"{fmt_count(c['posts'])}（{100*c['posts']/t30p:.1f}%）",
            f"{fmt_count(c['views'])}（{100*c['views']/t30v:.1f}%）",
        ])
    tbl = add_table(
        doc,
        ["话题桶", "7日个数", "7日帖子", "7日播放", "30日个数", "30日帖子", "30日播放"],
        bucket_rows,
        [4.0, 1.6, 2.6, 2.8, 1.8, 2.6, 2.8],
    )
    prevent_row_split(tbl)
    p(doc, "每个话题只归入一个主桶。例如 #lastchristmas 归入节日季（而不是音乐），#tiktokscaryhorrorcontest 归入官方活动（而不是节日季）。",
      size=9, color=MUTED, space_before=6)

    doc.add_heading("4.2 Top 20 播放量", level=2)
    add_picture_fit(doc, charts["top20_7"])
    add_picture_fit(doc, charts["top20_30"])

    doc.add_heading("4.3 单帖播放：头部内容还是大众参与", level=2)
    p(doc,
      "单帖播放 = 播放量 ÷ 帖子数。偏高说明少数爆款或媒体账号在带动（不适合做大众模板）；偏低且帖子多，说明普通人正在大量跟拍（更接近模板需求）。LIVE 激励标签普遍低于 2,200 播放/帖，就是任务式灌水。",
      size=11)
    add_picture_fit(doc, charts["scatter"])

    top_vpp7 = sorted(analysis.d7, key=lambda r: -r.vpp)[:6]
    low_vpp7 = sorted([r for r in analysis.d7 if r.posts >= 2000], key=lambda r: r.vpp)[:6]
    vpp_rows = []
    for r in top_vpp7:
        vpp_rows.append([f"7日高 {r.hashtag}", f"{fmt_count(r.vpp)}", f"第{r.rank}", r.bucket, "偏头部内容"])
    for r in low_vpp7:
        vpp_rows.append([f"7日低 {r.hashtag}", f"{fmt_count(r.vpp)}", f"第{r.rank}", r.bucket, "偏大众参与/灌水"])
    tbl = add_table(doc, ["话题", "单帖播放", "名次", "桶", "读法"], vpp_rows)
    prevent_row_split(tbl)
    p(doc, "", space_after=6)

    doc.add_heading("4.4 新冒头、持续热、退潮", level=2)
    add_picture_fit(doc, charts["lifecycle"])
    p(doc,
      f"新冒头 {len(analysis.new_tags)} 个，持续热 {len(analysis.sustain_tags)} 个，退潮 {len(analysis.fade_tags)} 个。"
      "持续热的 18 个里，除 #lastchristmas 外几乎全是选举标签（#bluewave、#electionday、#midterms、#vote 等）。"
      "也就是说：跨 7 日和 30 日都还热、又不是政治的话题，今天基本上只看出一个圣诞歌。",
      size=11)

    # notable new non-political
    notable_new = []
    for r in sorted(analysis.d7, key=lambda x: x.rank):
        if r.hashtag.lower() in analysis.new_tags and r.bucket != "美国中期选举/政治":
            if r.rank <= 50 or r.hashtag.lower() in {
                "#lastchristmas", "#veteransday", "#strangerthingsday",
                "#godzillaminuszero", "#transformers", "#livefest2026",
                "#livecanbeeasy", "#dj",
            }:
                notable_new.append(r)
    new_rows = [[
        r.hashtag, str(r.rank), f"{r.posts_raw} / {r.views_raw}",
        fmt_count(r.vpp), r.bucket.replace("TikTok官方活动/直播/创作者激励", "官方/直播激励"),
    ] for r in notable_new[:18]]
    doc.add_heading("7 日新冒头里值得看一眼的（已去掉大部分政治标签）", level=3)
    tbl = add_table(doc, ["话题", "7日排名", "帖子 / 播放", "单帖播放", "桶"], new_rows)
    prevent_row_split(tbl)

    fade_focus = [
        "#tiktokscaryhorrorcontest", "#tiktokthrillermysterycontest",
        "#halloweekend", "#stickerbanner", "#coderot", "#damehombro",
        "#imsosorry", "#halloweentransition", "#clayface", "#visionquest",
        "#youcanseeeverything", "#nnn", "#acosh", "#brandrisk",
    ]
    fade_rows = []
    for tag in fade_focus:
        r = row_by_tag(analysis.d30, tag)
        if not r:
            continue
        fade_rows.append([
            r.hashtag, str(r.rank), f"{r.posts_raw} / {r.views_raw}",
            fmt_count(r.vpp), r.bucket.replace("TikTok官方活动/直播/创作者激励", "官方/直播激励"),
        ])
    doc.add_heading("30 日仍在、7 日已消失的退潮样本", level=3)
    tbl = add_table(doc, ["话题", "30日排名", "帖子 / 播放", "单帖播放", "桶"], fade_rows,
                    [5.4, 2.0, 3.8, 2.2, 3.2])
    prevent_row_split(tbl)
    p(doc, "万圣节、官方恐怖/悬疑比赛、Code Rot、Dame Hombro、I'm So Sorry 都已经从近 7 日 Top 100 消失。它们可以当「刚刚过去的需求」来复盘，不宜再当新品主推。",
      size=10, color=MUTED, space_before=6)

    # researched cards
    doc.add_heading("4.5 可二创或看起来像机会的话题，逐个说明", level=2)
    p(doc, "只写查到了来源的判断。数据全部来自今日 CSV；「是什么」来自下方列出的公开链接。", size=10, color=MUTED)

    research_order = [
        "#lastchristmas", "#godzillaminuszero", "#transformers",
        "#tiktokscaryhorrorcontest", "#tiktokthrillermysterycontest",
        "#halloweentransition", "#stickerbanner", "#coderot",
        "#imsosorry", "#damehombro", "#youcanseeeverything",
        "#clayface", "#visionquest", "#acosh", "#brandrisk",
        "#loozecannon", "#captainsaveaho", "#veteransday",
        "#strangerthingsday", "#nnn", "#yorkshirewildlifepark",
        "#livefest2026", "#couplescostume",
    ]
    card_rows = []
    for tag in research_order:
        note = notes.get(tag)
        if not note:
            continue
        data, sig = data_pair(analysis, tag)
        card_rows.append([
            tag,
            sig or "—",
            note.get("verdict", ""),
            (note["what"] + " " + data)[:90] + ("…" if len(note["what"] + " " + data) > 90 else ""),
        ])
        doc.add_heading(f"{tag}　·　{note.get('verdict', '')}　·　{sig or '未进榜'}", level=3)
        bullet(doc, note["what"], bold_prefix="是什么：")
        bullet(doc, data, bold_prefix="数据：")
        bullet(doc, note["angle"], bold_prefix="能不能做：")
        para = p(doc, "来源：", size=9, color=MUTED, space_after=8)
        para.clear()
        r = para.add_run("来源：")
        set_run_font(r, 9, False, MUTED)
        add_hyperlink(para, note.get("source_label", note["source"]), note["source"], size=9)

    # 建议做
    doc.add_heading("4.6 建议做", level=2)
    recs = [
        {
            "title": "1. Shoulder Carry「I'm the One」一键扛肩翻身",
            "what": "一个人把另一个人扛上肩再翻转的双人动作，AI 版用两张照片生成。",
            "data": "ViralRemix 27.6K/天【第三方读数】；音频 308,343 条视频，每天约 +9,800（11/6）【第三方读数】；CapCut “Cause I'm The One” 11/6 用量 5,397【第三方读数】；Turnly 61 / Remake the Trend 55 位；X 7 天 49【已核实】。排名由昨日第 7 升到第 4。",
            "why": "音频使用量和模板使用量差了约 57 倍，是今天缺口最大的梗。真人版已经在峰值，AI 版仍在上升。",
            "how": "做「两张照片 → 扛肩翻身视频」一键页，目标是情侣和朋友档创作者。工具侧对标 Seedance 2.5、Kling O3 Edit。窗口约 5–7 天，今天就该上。",
            "risk": "动作有身体接触，生成时注意姿势崩坏和年龄审核。音频版权在 TikTok 侧解决，站点不要内置未授权歌曲。",
        },
        {
            "title": "2. Can I Ride 双人舞模板",
            "what": "SIDEPIECE × 95 South《Can I Ride》双人轮跳。",
            "data": "ViralRemix 24.3K/天，▲89%【第三方读数】；jumponthetrend 约 12M【估算】；X 7 天 23【已核实】。CapCut 未核实到主模板。排名第 6 → 第 5。",
            "why": "今天主榜里增速最快，而且没有被 CapCut 占住。",
            "how": "做「两张照片生成双人舞」模板，和 Shoulder Carry 共用双人上传界面。目标同样是情侣/朋友。越早上越能吃到上升段。",
            "risk": "舞蹈生成常见脚部和节拍对不齐。上线后要用 3–5 条样片盯住失败率。",
        },
        {
            "title": "3. #lastchristmas 圣诞情侣怀旧短片",
            "what": "每年 11 月被重新点亮的圣诞歌话题，内容是情侣、遗憾、雪景和旧照片对照。",
            "data": data_pair(analysis, "#lastchristmas")[0] + "。它是今天 18 个「持续热」话题里几乎唯一的非政治项。",
            "why": "选举噪音会很快过去，万圣节已经退潮，下一个大众情绪窗口就是圣诞。现在动手，比 12 月再追从容。",
            "how": "「一张或两张照片 → 20 秒冬日圣诞短片」：暖灯、细雪、旧胶片质感、对视或拥抱。面向情侣和家庭账号。站点只提供画面，用户到 TikTok 自行挂热门音频，避开 Wham! 录音版权。",
            "risk": "歌曲本身有版权；下雪、圣诞灯也是红海视觉，要靠情绪和人物一致性取胜，不要做成通用风景片。",
        },
        {
            "title": "4. Cat on Ultra Bee 宠物越野车",
            "what": "把宠物照片生成骑在越野摩托车上翘头起步的视频。",
            "data": "原帖 1.2M 播放，后续样片 579K / 323K；音频 2,434 条；Turnly 68 位【第三方读数】；X 0【已核实】。今日新上榜。",
            "why": "宠物圈和车友圈会交叉传播，模板用量还小，窗口约 4–6 天。",
            "how": "单张宠物照片上传，输出越野车翘头镜头。可以先做猫，再扩到狗。标题和封面直接写 Ultra Bee，方便搜索。",
            "risk": "车辆品牌外观不要做成可识别的官方广告片。注意宠物面部一致。",
        },
        {
            "title": "5. Then I Walk In（AI 版）",
            "what": "早期信号里的进门/亮相表演，AI 版把一张照片变成走进房间压过全场的短片。",
            "data": "ViralRemix 152/天，▲318%，话题 36.9M【第三方读数】；无 CapCut 专用模板。",
            "why": "基数还小但增速极高，适合用现成的人物行走/亮相能力快速试水。",
            "how": "单人照片 → 推门走入场景，加一点镜头让位和侧面眼神。不要一上来做复杂多镜。",
            "risk": "可能是假峰值。先上线轻量页，看 48 小时留存再加资源。",
        },
        {
            "title": "6. 冬日恐悚 / 悬疑反转短片（学格式，不追比赛标签）",
            "what": "万圣节官方恐怖比赛 30 日 2.2B 播放，悬疑比赛 403.2M 播放，现在都已离开 7 日榜。",
            "data": data_pair(analysis, "#tiktokscaryhorrorcontest")[0] + "。" + data_pair(analysis, "#tiktokthrillermysterycontest")[0] + "。",
            "why": "标签在退潮，但需求被验证过：用户愿意用短视频看吓一跳和看反转。冬天仍吃这类内容。",
            "how": "做两条常青能力：一张照片生成 10–15 秒跳吓短片；一张照片生成带反转的悬疑 POV。不要使用官方比赛名，也不要复用 Code Rot 那种绑着小黄人滤镜的玩法。",
            "risk": "过度血腥或写实暴力会踩平台规则。走暗示、阴影和节奏，不走写实伤害。",
        },
        {
            "title": "7. Shaking Head 宠物摇头",
            "what": "早期信号，宠物对着镜头摇头的卡点视频。",
            "data": "ViralRemix 486/天，▲134%；jumponthetrend 约 7.5M【估算】。",
            "why": "制作成本低，和 Cat on Ultra Bee 共享宠物上传入口，能一起养宠物品类。",
            "how": "单张宠物正面照 → 节奏摇头循环。作为宠物工具页上的第二个按钮即可。",
            "risk": "玩法简单，跟风会很快。当作配菜，不要当成本周唯一赌注。",
        },
        {
            "title": "8. Bicep Heart 照片生成视频（窗口还剩 3–5 天）",
            "what": "抬臂秀肌肉，另一只手在二头肌上合成心形。CapCut 现有模板多是静态图。",
            "data": "X 7 天 107,476【已核实】（昨 113,169）；每日 11/4 的 17,138 降到 11/9 的 13,831【已核实】；ViralRemix 约 12K/天，▲10%【第三方读数】。",
            "why": "真人波已过峰，但「一张照片生成视频」仍有空隙，现成静态模板正好说明视频版还没被做满。",
            "how": "单张半身照 → 3 秒抬臂比心。如果兵力只够做两三个新品，它排在 Shoulder Carry、Can I Ride 和圣诞模板之后。",
            "risk": "窗口短，过峰后再投放会浪费。身体变形（手臂比例）是主要失败点。",
        },
    ]
    for rec in recs:
        doc.add_heading(rec["title"], level=3)
        bullet(doc, rec["what"], bold_prefix="是什么：")
        bullet(doc, rec["data"], bold_prefix="数据：")
        bullet(doc, rec["why"], bold_prefix="为什么值得做：")
        bullet(doc, rec["how"], bold_prefix="具体做法：")
        bullet(doc, rec["risk"], bold_prefix="风险：")

    doc.add_heading("4.7 不建议做", level=2)
    nos = [
        ("美国中期选举 / 政治标签（#bluewave、#midterms、#vote、#democrats 等）",
         f"近 7 日播放的 {pol_share:.1f}% 来自这个桶（约 {fmt_count(pol_views)}），热度最高，但品牌和广告风险也最高。选举日是 11/3，新闻周期在往下走，不是消费娱乐需求。"),
        ("TikTok LIVE 激励标签（#livecanbeeasy、#livemonetization、#mylivejourney、#livefest2026）",
         "平台任务和直播赛事。单帖播放普遍很低（#livemonetization 约 1,058），是创作者为了完成任务在发，不是观众在找这种视频看。"),
        ("万圣节集群和比赛原标签（#halloweekend、#happyhalloween、#costume、两个 contest）",
         "30 日看起来巨大，是因为 10 月底被计入；它们已经不在 7 日榜，属于退潮。不要为过季标签再开一页。"),
        ("未授权影视 IP（#godzillaminuszero、#transformers、#strangerthingsday、#visionquest、#clayface、#disneynight、#talkingtom）",
         "有官方宣发或剧集档期在带热度。官方哥斯拉活动持续到 12/18，去抢未授权素材既有版权风险，也很难赢过官方导流。"),
        ("#loozecannon / Big Michael Michael",
         "用 AI 滤镜扮演迈克尔·杰克逊。说明「AI 变脸直播」有市场，但肖像权不适合做成一键产品。"),
        ("#yorkshirewildlifepark",
         "真实的动物园致死新闻，30 日仍有 2.87 亿播放。绝不能做成娱乐模板。"),
        ("#nnn（No Nut November）",
         "成人网络梗，内容政策和广告都过不了。"),
        ("#youcanseeeverything、#brandrisk、#acosh",
         "分别是纪录片反应梗、搏击赛事切片和 BookTok 新书讨论。单帖播放很高，但都不是用户上传自己照片就能复用的格式；ACOSH 还涉及小说版权。"),
        ("#stickerbanner、#coderot、#captainsaveaho",
         "前者是主页装饰工具（已有独立产品），后两者分别是过峰的滤镜恐怖梗和品牌不安全的老舞。"),
        ("#veteransday 商业模板",
         "明天就是退伍军人节，窗口极短，商业一键页很容易显得在消费纪念。"),
    ]
    for title, reason in nos:
        bullet(doc, reason, bold_prefix=title + " —— ")

    doc.add_heading("4.8 对 AI 一键视频站的结论", level=2)
    conclusions = [
        "Creative Center 的 News & Entertainment 榜不能代替 AI 梗榜。今天 7 日榜的主角是选举和 LIVE 任务，30 日榜的主角是刚结束的万圣节。主产品决策仍以 ViralRemix / Turnly / X 过滤后的 AI 梗为准。",
        "季节已经从万圣节切到圣诞。#lastchristmas 同时停在两份榜上，是这份行业榜今天最清楚的产品信号。万圣节比赛则留下了「短恐悚 / 短悬疑」这个被十亿播放验证过的格式，而不是两个该继续追的标签。",
        "舞类和双人动作仍然是一键站的基本盘（Shoulder Carry、Can I Ride、Ba Ba Ba）。它们不会出现在 N&E 榜里，因为分类就不收录这类娱乐舞蹈。",
        "高单帖播放的娱乐标签（维多利亚的秘密时装秀、H3、Brand Risk、You Can See Everything）几乎都是头部媒体或明星事件，带不动「上传自己的照片」这种产品。",
        "从明天起，用昨日 CSV 对比就能标出新进榜和上升最快的话题。今日没有这项数据，不是漏做，是第一天没有昨日基数，且原页面不提供升降。",
    ]
    for line in conclusions:
        bullet(doc, line)

    # 五、行动清单
    doc.add_heading("五、今日行动清单", level=1)
    actions = [
        "今天内部排期：先上 Shoulder Carry 双人扛肩，再上 Can I Ride 双人舞。两个共用同一套双人上传。",
        "本周内开工圣诞页：#lastchristmas 情绪的情侣/家庭冬日短片，画面自建，音频留给 TikTok。",
        "并行做 Cat on Ultra Bee，并把宠物摇头做成同一页面上的第二个按钮。",
        "用现成行走/亮相能力试水 Then I Walk In，只做轻量页，48 小时后再决定加不加资源。",
        "Bicep Heart 视频版如果还有手，就做；没手就放弃，窗口只剩大约 3–5 天。",
        "不要为政治标签、LIVE Fest、万圣节比赛名、哥斯拉/变形金刚/幻视/Clayface 开新页。",
        "把今日这份 Creative Center CSV 存成「昨日基准」。明天的日报要算出 7 日和 30 日的新进榜、掉榜和名次变化。",
        "Ba Ba Ba 仍在峰值（46.7K/天），可以维持「两张照片生成双人舞」但不作为新品第一优先。切鱼梗的 CapCut 已经做开，只适合文案变体，不再投入模板研发。",
    ]
    for i, line in enumerate(actions, 1):
        bullet(doc, line, bold_prefix=f"{i}. ")

    p(doc,
      "图表文件目录：与本报告一同生成的 PNG，可单独发到 Lark。若明天提供昨日 CSV，脚本会自动补上排名升降列。",
      size=9, color=MUTED, space_before=12)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return str(out)


def main():
    ap = argparse.ArgumentParser(description="Build the visual AI meme daily report")
    ap.add_argument("--date")
    ap.add_argument("--md", required=True)
    ap.add_argument("--cc-csv", required=True)
    ap.add_argument("--prev-cc-csv")
    ap.add_argument("--tag-notes")
    ap.add_argument("--remix-csv")
    ap.add_argument("--heat-json")
    ap.add_argument("--heat-csv")
    ap.add_argument("--cc-trends-csv")
    ap.add_argument("--out-docx", required=True)
    ap.add_argument("--chart-dir", required=True)
    ap.add_argument("--font", default=str(P.FONT))
    args = ap.parse_args()

    digest = parse_digest(Path(args.md).read_text(encoding="utf-8"))
    report_date = args.date or digest.date
    analysis = analyze_cc(args.cc_csv, args.prev_cc_csv)
    notes = load_notes(args.tag_notes)

    remix_summary = {}
    remix_points = []
    if args.remix_csv:
        remix_videos = load_remix_csv(args.remix_csv)
        remix_summary = summarize_remixes(remix_videos)
        for meme, plats in remix_summary.items():
            for plat, st in plats.items():
                if not st.enough:
                    continue
                st.nick = NICK.get(st.meme, st.meme)
                st.stage = (MEME_META.get(st.meme) or {}).get("chart_stage", "")
                remix_points.append(st)

    heat_map = {}
    heat_path = getattr(args, "heat_json", None) or getattr(args, "heat_csv", None)
    if heat_path:
        heat_map = load_heat(heat_path)

    cc_trends = {}
    if args.cc_trends_csv:
        cc_trends = load_cc_trends(args.cc_trends_csv)

    heat = []
    for row in digest.ranking:
        val, met = parse_core_metric(row["core"])
        if val is None:
            continue
        heat.append({"rank": row["rank"], "name": row["name"], "value": val, "metric": met})
    x_daily = extract_x_daily(digest)
    extra = {
        "ai_heat": heat,
        "x_daily": x_daily,
        "matrix": matrix_from_digest(digest),
        "highlight_tags": highlight_tags(),
        "label_tags": scatter_label_tags(),
        "remix_points": remix_points,
        "heat": heat_map,
        "cc_trends": cc_trends,
    }
    charts = make_all_charts(Path(args.chart_dir), args.font, analysis, extra)
    path = build_docx_v4(digest, analysis, charts, notes, args.out_docx, report_date, remix_summary, heat_map, cc_trends)
    print("DOCX", path)
    for k, v in charts.items():
        print("CHART", k, v)
    print("NEW", len(analysis.new_tags), "SUSTAIN", len(analysis.sustain_tags), "FADE", len(analysis.fade_tags))
    print("HAS_PREV", analysis.has_prev)
    print("ENTRIES", len(digest.entries), "RANK", len(digest.ranking), "EARLY", len(digest.early))
    print("REMIX_MEMES", list(remix_summary.keys()))
    for meme, plats in remix_summary.items():
        for plat, st in plats.items():
            print(f"REMIX {meme} {plat} n={st.n} median={st.median_share} weighted={st.weighted_share} {st.verdict}")


if __name__ == "__main__":
    main()
