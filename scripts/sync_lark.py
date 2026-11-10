#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build idempotent Lark Base JSON batches for the AI meme digest.

The user-Lark-base MCP connector is the only write path (no app secret on
this box). This script:

  1. Reads the local CSVs / index rows
  2. Writes per-table JSON batches under
     data/lark-batches/<as-of>-<table_key>.json
     already split into chunks of at most 500 records, in create_records shape
  Lark batches are written only when --sync-lark is passed or sync_lark is true.
  3. Never invents values; omits empty fields instead of sending blank strings
  4. Uses 去重键 so a rerun can skip keys already in the Base

MCP write rules (user-Lark-base create_records only; no app secret on this box):
  - records must be an inlined JSON array of {fields:{...}}. Passing
    "$file:/path.json" stays a string and fails with "expected array".
  - Max 500 records per call. Prefer the compact *.sXX.json files (~40
    rows, or 14/11/7 for leftover splits) so the tool-call payload stays
    small enough to inline.
  - URL fields (详情链接, Lark链接, 主页链接, 链接) must be {link, text}
    objects. Plain strings return lark_code 1254068 URLFieldConvFail.
  - Do not delete or rename the default table tblXzNbv84sJpzfO (Table).
  - Include authorizedBy: ["pt23u"] on write calls.

After tables exist, an agent should:
  - search_records for 去重键 (page through if needed) and write
    existing_keys.json as {table_key: [去重键, ...]}
  - rerun this script with --existing-keys so already-loaded keys are
    omitted from the new batches
  - call create_records with each remaining compact *.sXX.json array
  - verify with search_records totals and update lark_base_schema.json
    loaded counts

Date fields are millisecond timestamps at 00:00:00 in the Base timezone
(America/Los_Angeles, as returned by get_base). That way a calendar date
displays as that same day in the Base UI.

Usage:
  python scripts/sync_lark.py --as-of 2026-11-10 --sync-lark \
      --existing-keys data/lark-batches/2026-11-10-existing-keys.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import paths as P

APP_TOKEN = "KakJbMCKNaHiaws7u2ZuqNfIttg"
BASE_URL = "https://rlarkus1gkty4r86.usttp.larksuite.com/base/KakJbMCKNaHiaws7u2ZuqNfIttg"
BASE_TZ = ZoneInfo("America/Los_Angeles")
BATCH_DIR = P.LARK_BATCH_DIR
SCHEMA_PATH = P.LARK_SCHEMA
MAX_RECORDS = 500

# Lark field types
TEXT, NUMBER, SELECT, MULTI, DATE, CHECKBOX, URL = 1, 2, 3, 4, 5, 7, 15

REGIONS = ["US", "GB", "AU", "CA", "DE", "JP", "KR", "FR", "NL"]
PERIODS = ["7日", "30日"]
VERDICTS = ["做", "观望", "不做"]
PLATFORMS = ["TikTok", "Instagram", "X", "YouTube", "CapCut", "其他"]
BACKTEST_RESULTS = ["对", "错", "数据不足"]
WATCH_STATUS = ["候选", "已选"]
AUDIENCE_DIMS = ["年龄", "地区", "兴趣"]
PARTS = ["主榜", "早期信号"]
AI_FLAGS = ["yes", "no", "unclear"]
VERIFY_TAGS = ["【已核实】", "【第三方读数】", "【估算】"]


def date_prop():
    return {"date_formatter": "yyyy-MM-dd", "auto_fill": False}


def num_prop(fmt: str = "0"):
    return {"formatter": fmt}


def sel_prop(names: list[str]):
    return {"options": [{"name": n} for n in names]}


# Initial field lists. First field is the primary field (去重键, Text).
TABLES = {
    "cc_rank_snapshot": {
        "name": "CC榜单快照",
        "dedupe": "去重键",
        "description": "Creative Center Top 100 榜单快照，一行一个话题在某一抓取日、地区、周期下的排名。",
        "fields": [
            {"field_name": "去重键", "type": TEXT},
            {"field_name": "抓取日期", "type": DATE, "property": date_prop()},
            {"field_name": "地区", "type": SELECT, "property": sel_prop(REGIONS)},
            {"field_name": "筛选行业", "type": TEXT},
            {"field_name": "行业", "type": TEXT},
            {"field_name": "周期", "type": SELECT, "property": sel_prop(PERIODS)},
            {"field_name": "排名", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "话题", "type": TEXT},
            {"field_name": "发帖数", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "发帖数原文", "type": TEXT},
            {"field_name": "播放量", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "播放量原文", "type": TEXT},
            {"field_name": "播放/发帖", "type": NUMBER, "property": num_prop("0.00")},
            {"field_name": "排名变化", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "详情ID", "type": TEXT},
            {"field_name": "详情链接", "type": URL},
        ],
    },
    "cc_hashtag_curve": {
        "name": "CC话题曲线",
        "dedupe": "去重键",
        "description": "Creative Center 话题详情页的相对热度指数（0–100），一行一个话题在某一周期下的一天。",
        "fields": [
            {"field_name": "去重键", "type": TEXT},
            {"field_name": "抓取日期", "type": DATE, "property": date_prop()},
            {"field_name": "话题", "type": TEXT},
            {"field_name": "地区", "type": SELECT, "property": sel_prop(REGIONS)},
            {"field_name": "周期", "type": SELECT, "property": sel_prop(PERIODS)},
            {"field_name": "日期", "type": DATE, "property": date_prop()},
            {"field_name": "热度指数", "type": NUMBER, "property": num_prop("0.0")},
            {"field_name": "详情ID", "type": TEXT},
            {"field_name": "详情链接", "type": URL},
        ],
    },
    "cc_hashtag_audience": {
        "name": "CC话题受众",
        "dedupe": "去重键",
        "description": "话题详情页的受众拆分。年龄写入占比；国家写入人气指数，不是百分比。",
        "fields": [
            {"field_name": "去重键", "type": TEXT},
            {"field_name": "抓取日期", "type": DATE, "property": date_prop()},
            {"field_name": "话题", "type": TEXT},
            {"field_name": "地区", "type": SELECT, "property": sel_prop(REGIONS)},
            {"field_name": "周期", "type": SELECT, "property": sel_prop(PERIODS)},
            {"field_name": "维度", "type": SELECT, "property": sel_prop(AUDIENCE_DIMS)},
            {"field_name": "分组", "type": TEXT},
            {"field_name": "占比", "type": NUMBER, "property": num_prop("0.00")},
            {"field_name": "人气指数", "type": NUMBER, "property": num_prop("0.00")},
            {"field_name": "数值说明", "type": TEXT},
            {"field_name": "详情ID", "type": TEXT},
        ],
    },
    "meme_daily_tracker": {
        "name": "梗每日追踪",
        "dedupe": "去重键",
        "description": "每个报告日、每条梗一行，含结论、五项评分和当时记下的主热度。",
        "fields": [
            {"field_name": "去重键", "type": TEXT},
            {"field_name": "日期", "type": DATE, "property": date_prop()},
            {"field_name": "梗", "type": TEXT},
            {"field_name": "规范ID", "type": TEXT},
            {"field_name": "结论", "type": SELECT, "property": sel_prop(VERDICTS)},
            {"field_name": "综合评分", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "热度分", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "趋势分", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "分享率分", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "竞争分", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "窗口分", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "主热度口径", "type": TEXT},
            {"field_name": "主热度值", "type": NUMBER, "property": num_prop("0.00")},
            {"field_name": "主热度日期", "type": DATE, "property": date_prop()},
            {"field_name": "主热度来源", "type": TEXT},
            {"field_name": "X近7日发帖", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "X统计区间", "type": TEXT},
            {"field_name": "X来源说明", "type": TEXT},
            {"field_name": "ViralRemix日新增", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "ViralRemix日期", "type": DATE, "property": date_prop()},
            {"field_name": "ViralRemix完整", "type": CHECKBOX},
            {"field_name": "CC话题", "type": TEXT},
            {"field_name": "CC地区", "type": SELECT, "property": sel_prop(REGIONS)},
            {"field_name": "CC近7日排名", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "CC近30日排名", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "CC30日指数", "type": NUMBER, "property": num_prop("0.0")},
            {"field_name": "CC指数日期", "type": DATE, "property": date_prop()},
            {"field_name": "二创中位分享率", "type": NUMBER, "property": num_prop("0.00")},
            {"field_name": "二创样本数", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "二创平台", "type": SELECT, "property": sel_prop(PLATFORMS)},
            {"field_name": "起火说明", "type": TEXT},
            {"field_name": "已火天数", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "高峰状态", "type": TEXT},
            {"field_name": "窗口", "type": TEXT},
            {"field_name": "部分", "type": SELECT, "property": sel_prop(PARTS)},
            {"field_name": "来源标签", "type": TEXT},
            {"field_name": "备注", "type": TEXT},
        ],
    },
    "remix_videos": {
        "name": "二创视频",
        "dedupe": "去重键",
        "description": "高播二创样本，一行一个视频，附分享率和点赞率。",
        "fields": [
            {"field_name": "去重键", "type": TEXT},
            {"field_name": "日报日期", "type": DATE, "property": date_prop()},
            {"field_name": "梗", "type": TEXT},
            {"field_name": "链接", "type": URL},
            {"field_name": "平台", "type": SELECT, "property": sel_prop(PLATFORMS)},
            {"field_name": "创作者", "type": TEXT},
            {"field_name": "发布日期", "type": DATE, "property": date_prop()},
            {"field_name": "播放", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "点赞", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "分享", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "评论", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "收藏", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "是否AI", "type": SELECT, "property": sel_prop(AI_FLAGS)},
            {"field_name": "分享率", "type": NUMBER, "property": num_prop("0.00")},
            {"field_name": "点赞率", "type": NUMBER, "property": num_prop("0.00")},
            {"field_name": "分享点赞比", "type": NUMBER, "property": num_prop("0.00")},
            {"field_name": "是否头部样本", "type": CHECKBOX},
            {"field_name": "样本排名", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "核实标记", "type": TEXT},
            {"field_name": "来源", "type": TEXT},
            {"field_name": "备注", "type": TEXT},
        ],
    },
    "backtest": {
        "name": "回测",
        "dedupe": "去重键",
        "description": "推荐「做」后第 3 天主热度是否仍在涨。",
        "fields": [
            {"field_name": "去重键", "type": TEXT},
            {"field_name": "推荐日", "type": DATE, "property": date_prop()},
            {"field_name": "梗", "type": TEXT},
            {"field_name": "规范ID", "type": TEXT},
            {"field_name": "当时结论", "type": SELECT, "property": sel_prop(VERDICTS)},
            {"field_name": "评分", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "主热度口径", "type": TEXT},
            {"field_name": "基线值", "type": NUMBER, "property": num_prop("0.00")},
            {"field_name": "基线日期", "type": DATE, "property": date_prop()},
            {"field_name": "D+3日期", "type": DATE, "property": date_prop()},
            {"field_name": "D+3值", "type": NUMBER, "property": num_prop("0.00")},
            {"field_name": "D+3来源", "type": TEXT},
            {"field_name": "结果", "type": SELECT, "property": sel_prop(BACKTEST_RESULTS)},
            {"field_name": "说明", "type": TEXT},
            {"field_name": "结论卡一句", "type": TEXT},
        ],
    },
    "watchlist": {
        "name": "监控账号",
        "dedupe": "去重键",
        "description": "TikTok / Instagram 搬运号、模板号、AI 特效号候选名单。",
        "fields": [
            {"field_name": "去重键", "type": TEXT},
            {"field_name": "状态", "type": SELECT, "property": sel_prop(WATCH_STATUS)},
            {"field_name": "排序", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "平台", "type": SELECT, "property": sel_prop(PLATFORMS)},
            {"field_name": "handle", "type": TEXT},
            {"field_name": "主页链接", "type": URL},
            {"field_name": "类型", "type": TEXT},
            {"field_name": "显示名", "type": TEXT},
            {"field_name": "粉丝数", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "粉丝统计日", "type": DATE, "property": date_prop()},
            {"field_name": "粉丝来源", "type": TEXT},
            {"field_name": "粉丝标签", "type": SELECT, "property": sel_prop(VERIFY_TAGS)},
            {"field_name": "视频数", "type": NUMBER, "property": num_prop("0")},
            {"field_name": "开号日期", "type": DATE, "property": date_prop()},
            {"field_name": "更新频率", "type": TEXT},
            {"field_name": "早发证据梗", "type": TEXT},
            {"field_name": "证据日期", "type": TEXT},
            {"field_name": "证据链接", "type": TEXT},
            {"field_name": "证据说明", "type": TEXT},
            {"field_name": "语言", "type": TEXT},
            {"field_name": "地区", "type": TEXT},
            {"field_name": "地区来源", "type": TEXT},
            {"field_name": "推荐理由", "type": TEXT},
            {"field_name": "注意", "type": TEXT},
            {"field_name": "主页核对", "type": TEXT},
            {"field_name": "简介", "type": TEXT},
        ],
    },
    "digest_index": {
        "name": "日报索引",
        "dedupe": "去重键",
        "description": "每天每版日报一条，指向 Lark Wiki 文档。",
        "fields": [
            {"field_name": "去重键", "type": TEXT},
            {"field_name": "日期", "type": DATE, "property": date_prop()},
            {"field_name": "版本", "type": TEXT},
            {"field_name": "Lark链接", "type": URL},
            {"field_name": "做的梗", "type": TEXT},
            {"field_name": "观望的梗", "type": TEXT},
            {"field_name": "不做的梗", "type": TEXT},
            {"field_name": "备注", "type": TEXT},
        ],
    },
}

# Future CC detail-page captures → table mapping (also stored in schema JSON)
FUTURE_CC_CAPTURE = {
    "daily_curve_7d": "CC话题曲线（周期=7日，热度指数）",
    "daily_curve_30d": "CC话题曲线（周期=30日，热度指数）",
    "audience_age": "CC话题受众（维度=年龄，分组如 18-24，占比）",
    "audience_regions": "CC话题受众（维度=地区，分组为国家/地区名，占比）",
    "related_interests": "CC话题受众（维度=兴趣，分组为兴趣名，占比）",
    "related_videos_and_creators": "暂不入库单独表。详情抓取时若页面展示相关视频和创作者，先写入当日抓取原始 JSON，再视情况扩「二创视频」或新建「CC相关视频」表。不要把这些行混进受众表。",
    "note": "详情页从榜单行的分析链接进入，URL 形态 /creative/creativeCenter/trends/hashtag/<详情ID>?region=<地区>&period=<7|30>。页面是相对指数 0–100，不是绝对播放。同时记下抓取日期、地区、周期、详情ID。年龄、地区、兴趣分布尽量一次抓全，方便按国家比较。",
}


def date_to_ms(value: str | date | None) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        d = value
    else:
        s = str(value).strip()
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
        if not m:
            return None
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=BASE_TZ)
    return int(dt.timestamp() * 1000)


def parse_count(s: str | None):
    """Parse Creative Center display counts like 87.6K, 2.2B. Returns (number, original) or (None, original)."""
    if s is None:
        return None, ""
    raw = str(s).strip()
    if raw == "":
        return None, ""
    t = raw.replace(",", "").upper()
    try:
        if t.endswith("B"):
            n = float(t[:-1]) * 1_000_000_000
        elif t.endswith("M"):
            n = float(t[:-1]) * 1_000_000
        elif t.endswith("K"):
            n = float(t[:-1]) * 1_000
        else:
            n = float(t)
        r = round(n)
        if abs(n - r) < 1e-6:
            n = int(r)
        return n, raw
    except ValueError:
        return None, raw


def parse_number(s):
    if s in (None, ""):
        return None
    try:
        n = float(str(s).strip())
        if n == int(n):
            return int(n)
        return n
    except ValueError:
        return None


def parse_bool(s):
    if s in (None, ""):
        return None
    v = str(s).strip().lower()
    if v in ("true", "yes", "1", "是"):
        return True
    if v in ("false", "no", "0", "否"):
        return False
    return None


def period_label(days) -> str | None:
    s = str(days).strip()
    if s in ("7", "7日"):
        return "7日"
    if s in ("30", "30日"):
        return "30日"
    return None


def part_label(v) -> str | None:
    s = (v or "").strip()
    if s == "main":
        return "主榜"
    if s == "early":
        return "早期信号"
    if s in PARTS:
        return s
    return None


def platform_label(v) -> str | None:
    s = (v or "").strip()
    if not s:
        return None
    if s in PLATFORMS:
        return s
    return "其他"


def extract_detail_id(url: str) -> str:
    if not url:
        return ""
    m = re.search(r"/hashtag/(\d+)", url)
    return m.group(1) if m else ""


def extract_region(url: str) -> str:
    if not url:
        return ""
    m = re.search(r"[?&]region=([A-Z]{2})", url, re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"[?&]countryCode=([A-Z]{2})", url, re.I)
    return m.group(1).upper() if m else ""



URL_FIELDS = {
    "详情链接", "Lark链接", "主页链接", "链接",
}


def as_url(v):
    if not v:
        return None
    s = str(v).strip()
    if not s.startswith("http"):
        return None
    return {"link": s, "text": s}


def fields_clean(d: dict) -> dict:
    """Drop None / empty-string fields. Keep False and 0."""
    out = {}
    for k, v in d.items():
        if v is None or v == "":
            continue
        if k in URL_FIELDS:
            v = as_url(v) if not isinstance(v, dict) else v
            if v is None:
                continue
        out[k] = v
    return out


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(Path(path).read_text(encoding="utf-8-sig").splitlines()))


def load_tag_ids(as_of: str) -> dict[str, str]:
    path = P.resolve(as_of, "cc-tag-ids.json", f"cc_tag_ids_{as_of}.json")
    ids = json.loads(path.read_text()) if path.exists() else {}
    # Also harvest IDs from the trend CSV URLs
    trend = P.resolve(as_of, "cc-hashtag-trends.csv", f"cc_hashtag_trends_{as_of}.csv")
    if trend.exists():
        for r in read_csv(trend):
            hid = extract_detail_id(r.get("detail_url") or "")
            tag = (r.get("hashtag") or "").lstrip("#").lower()
            if hid and tag and tag not in ids:
                ids[tag] = hid
    return ids


def detail_url(tag_id: str, region: str, period_days: str) -> str:
    if not tag_id:
        return ""
    return (
        f"https://ads.tiktok.com/creative/creativeCenter/trends/hashtag/{tag_id}"
        f"?region={region}&period={period_days}"
    )


def chunk(records, n=MAX_RECORDS):
    for i in range(0, len(records), n):
        yield records[i : i + n]


# ---------- builders ----------

def _combined_top100_rows(path: Path, as_of: str, tag_ids: dict) -> list[dict]:
    """One file covering every region. Region comes from the row, not the filename."""
    rows = []
    for r in read_csv(path):
        period = period_label(r.get("period_days"))
        tag = (r.get("hashtag") or "").strip()
        region = (r.get("region") or "").strip() or "US"
        rank = parse_number(r.get("rank"))
        posts, posts_raw = parse_count(r.get("posts"))
        views, views_raw = parse_count(r.get("views"))
        ratio = None
        if posts and views and posts != 0:
            ratio = round(views / posts, 2)
        key_tag = tag.lstrip("#").lower()
        tid = (r.get("detail_id") or "").strip() or tag_ids.get(key_tag, "")
        period_days = "7" if period == "7日" else "30" if period == "30日" else ""
        rows.append(fields_clean({
            "去重键": f"{as_of}|{region}|{period}|{rank}|{tag}",
            "抓取日期": date_to_ms(as_of),
            "地区": region if region in REGIONS else None,
            "筛选行业": "News & Entertainment",
            "行业": (r.get("industry") or "").strip(),
            "周期": period,
            "排名": rank,
            "话题": tag,
            "发帖数": posts,
            "发帖数原文": posts_raw,
            "播放量": views,
            "播放量原文": views_raw,
            "播放/发帖": ratio,
            "详情ID": tid,
            "详情链接": detail_url(tid, region, period_days),
        }))
    return rows


def build_cc_rank_snapshot(as_of: str, tag_ids: dict, prev_ranks: dict | None = None) -> list[dict]:
    """Prefer the combined Top 100 file. Otherwise read per-region files."""
    combined = P.resolve(as_of, "cc-top100.csv", f"{as_of}_NewsEnt_top100_all.csv")
    if combined.exists():
        return _combined_top100_rows(combined, as_of, tag_ids)
    rows = []
    files = P.per_region_top100_files()
    for path in files:
        file_date, file_region, file_industry = P.parse_top100_filename(path.name, as_of)
        industry_filter = {
            "NewsEnt": "News & Entertainment",
        }.get(file_industry, file_industry)
        for r in read_csv(path):
            period = period_label(r.get("period_days"))
            tag = (r.get("hashtag") or "").strip()
            rank = parse_number(r.get("rank"))
            posts, posts_raw = parse_count(r.get("posts"))
            views, views_raw = parse_count(r.get("views"))
            ratio = None
            if posts and views and posts != 0:
                ratio = round(views / posts, 2)
            key_tag = tag.lstrip("#").lower()
            tid = tag_ids.get(key_tag, "")
            period_days = "7" if period == "7日" else "30" if period == "30日" else ""
            url = detail_url(tid, file_region, period_days)
            delta = None
            if prev_ranks is not None:
                prev_key = f"{file_region}|{period}|{tag}"
                if prev_key in prev_ranks and rank is not None:
                    delta = prev_ranks[prev_key] - rank  # positive = rose
            key = f"{file_date}|{file_region}|{period}|{rank}|{tag}"
            rows.append(fields_clean({
                "去重键": key,
                "抓取日期": date_to_ms(file_date),
                "地区": file_region,
                "筛选行业": industry_filter,
                "行业": (r.get("industry") or "").strip(),
                "周期": period,
                "排名": rank,
                "话题": tag,
                "发帖数": posts,
                "发帖数原文": posts_raw,
                "播放量": views,
                "播放量原文": views_raw,
                "播放/发帖": ratio,
                "排名变化": delta,
                "详情ID": tid,
                "详情链接": url,
            }))
    return rows


def build_cc_hashtag_curve(as_of: str, tag_ids: dict) -> list[dict]:
    path = P.resolve(as_of, "cc-hashtag-trends.csv", f"cc_hashtag_trends_{as_of}.csv")
    if not path.exists():
        cands = P.glob_many("*-cc-hashtag-trends.csv", "cc_hashtag_trends_*.csv")
        if not cands:
            return []
        path = cands[-1]
        m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
        if m:
            as_of = m.group(1)
    rows = []
    for r in read_csv(path):
        status = (r.get("status") or "found").strip().lower()
        if status not in ("", "found"):
            continue
        if not r.get("date") or r.get("value") in (None, ""):
            continue
        period = period_label(r.get("period_days"))
        tag = (r.get("hashtag") or "").strip()
        region = (r.get("region") or extract_region(r.get("detail_url") or "") or "US").strip()
        tid = (r.get("detail_id") or "").strip() or extract_detail_id(r.get("detail_url") or "") or tag_ids.get(tag.lstrip("#").lower(), "")
        key = f"{as_of}|{tag}|{region}|{period}|{r['date']}"
        rows.append(fields_clean({
            "去重键": key,
            "抓取日期": date_to_ms(as_of),
            "话题": tag,
            "地区": region if region in REGIONS else None,
            "周期": period,
            "日期": date_to_ms(r["date"]),
            "热度指数": parse_number(r.get("value")),
            "详情ID": tid,
            "详情链接": r.get("detail_url") or detail_url(tid, region, "7" if period == "7日" else "30"),
        }))
    return rows


def _popularity_index(raw: str):
    """Parse '1 (800.56)' into (rank, index). Index is not a percentage."""
    text = (raw or "").strip()
    index_match = re.search(r"\(([\d.]+)\)", text)
    index = float(index_match.group(1)) if index_match else None
    rank_match = re.match(r"(\d+)", text)
    rank = int(rank_match.group(1)) if rank_match else None
    return rank, index


def build_cc_hashtag_audience(as_of: str, tag_ids: dict | None = None) -> list[dict]:
    path = P.resolve(as_of, "cc-hashtag-detail.json", f"cc_hashtag_detail_{as_of}.json")
    if not path.exists():
        return []
    details = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for detail in details:
        tag_raw = (detail.get("hashtag") or "").strip()
        tag = tag_raw if tag_raw.startswith("#") else f"#{tag_raw}"
        tag_key = tag.lstrip("#")
        region = (detail.get("region") or "US").strip()
        period = period_label(detail.get("period_days"))
        tid = str(detail.get("detail_id") or (tag_ids or {}).get(tag_key, "") or "")
        for age in detail.get("age") or []:
            bucket = age.get("bucket") or ""
            rows.append(fields_clean({
                "去重键": f"{as_of}|{tag_key}|{region}|{period}|年龄|{bucket}",
                "抓取日期": date_to_ms(as_of),
                "话题": tag,
                "地区": region if region in REGIONS else None,
                "周期": period,
                "维度": "年龄",
                "分组": bucket,
                "占比": parse_number(age.get("pct")),
                "详情ID": tid,
                "数值说明": "年龄占比（%）",
            }))
        for country in detail.get("regions") or []:
            name = country.get("country") or ""
            rank, index = _popularity_index(country.get("pct_or_rank") or "")
            note = "地区人气指数（不是占比）"
            if rank:
                note = f"{note}；排名 {rank}"
            rows.append(fields_clean({
                "去重键": f"{as_of}|{tag_key}|{region}|{period}|地区|{name}",
                "抓取日期": date_to_ms(as_of),
                "话题": tag,
                "地区": region if region in REGIONS else None,
                "周期": period,
                "维度": "地区",
                "分组": name,
                "人气指数": index,
                "详情ID": tid,
                "数值说明": note,
            }))
    return rows


def build_meme_daily_tracker() -> list[dict]:
    path = P.TRACKER
    if not path.exists():
        return []
    rows = []
    for r in read_csv(path):
        cid = r.get("canonical_id") or r.get("meme")
        key = f"{r.get('date')}|{cid}"
        part = part_label(r.get("part"))
        rows.append(fields_clean({
            "去重键": key,
            "日期": date_to_ms(r.get("date")),
            "梗": r.get("meme"),
            "规范ID": r.get("canonical_id"),
            "结论": r.get("verdict") if r.get("verdict") in VERDICTS else None,
            "综合评分": parse_number(r.get("score")),
            "热度分": parse_number(r.get("score_heat")),
            "趋势分": parse_number(r.get("score_trend")),
            "分享率分": parse_number(r.get("score_share")),
            "竞争分": parse_number(r.get("score_competition")),
            "窗口分": parse_number(r.get("score_window")),
            "主热度口径": r.get("primary_heat_metric"),
            "主热度值": parse_number(r.get("primary_heat_value")),
            "主热度日期": date_to_ms(r.get("primary_heat_date")),
            "主热度来源": r.get("primary_heat_source"),
            "X近7日发帖": parse_number(r.get("x_7d_posts")),
            "X统计区间": r.get("x_7d_range"),
            "X来源说明": r.get("x_7d_source"),
            "ViralRemix日新增": parse_number(r.get("viralremix_new_videos")),
            "ViralRemix日期": date_to_ms(r.get("viralremix_date")),
            "ViralRemix完整": parse_bool(r.get("viralremix_complete")),
            "CC话题": r.get("cc_tag"),
            "CC地区": r.get("cc_region") if r.get("cc_region") in REGIONS else None,
            "CC近7日排名": parse_number(r.get("cc_rank_7d")),
            "CC近30日排名": parse_number(r.get("cc_rank_30d")),
            "CC30日指数": parse_number(r.get("cc_index_30d")),
            "CC指数日期": date_to_ms(r.get("cc_index_30d_date")),
            "二创中位分享率": parse_number(r.get("remix_median_share_rate")),
            "二创样本数": parse_number(r.get("remix_n")),
            "二创平台": platform_label(r.get("remix_platform")),
            "起火说明": r.get("ignite_date"),
            "已火天数": parse_number(r.get("days_hot")),
            "高峰状态": r.get("peak_status"),
            "窗口": r.get("window"),
            "部分": part,
            "来源标签": r.get("source_tag"),
            "备注": r.get("notes"),
        }))
    return rows


def build_remix_videos(as_of: str) -> list[dict]:
    path = P.resolve(as_of, "remix-stats.csv", f"remix_stats_{as_of}.csv")
    if not path.exists():
        cands = P.glob_many("*-remix-stats.csv", "remix_stats_*.csv")
        if not cands:
            return []
        path = cands[-1]
        m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
        if m:
            as_of = m.group(1)
    rows = []
    for r in read_csv(path):
        link = (r.get("link") or "").strip()
        key = f"{as_of}|{link}"
        rows.append(fields_clean({
            "去重键": key,
            "日报日期": date_to_ms(as_of),
            "梗": r.get("meme"),
            "链接": link if link.startswith("http") else None,
            "平台": platform_label(r.get("platform")),
            "创作者": r.get("creator"),
            "发布日期": date_to_ms(r.get("date")),
            "播放": parse_number(r.get("views")),
            "点赞": parse_number(r.get("likes")),
            "分享": parse_number(r.get("shares")),
            "评论": parse_number(r.get("comments")),
            "收藏": parse_number(r.get("saves")),
            "是否AI": r.get("is_AI") if r.get("is_AI") in AI_FLAGS else None,
            "分享率": parse_number(r.get("share_rate")),
            "点赞率": parse_number(r.get("like_rate")),
            "分享点赞比": parse_number(r.get("shares_per_like")),
            "是否头部样本": parse_bool(r.get("in_top_sample")),
            "样本排名": parse_number(r.get("sample_rank")),
            "核实标记": r.get("verified"),
            "来源": r.get("source"),
            "备注": r.get("notes"),
        }))
    return rows


def build_backtest() -> list[dict]:
    path = P.BACKTEST_CSV
    if not path.exists():
        return []
    rows = []
    for r in read_csv(path):
        cid = r.get("canonical_id") or r.get("meme")
        key = f"{r.get('recommend_date')}|{cid}"
        rows.append(fields_clean({
            "去重键": key,
            "推荐日": date_to_ms(r.get("recommend_date")),
            "梗": r.get("meme"),
            "规范ID": r.get("canonical_id"),
            "当时结论": r.get("verdict") if r.get("verdict") in VERDICTS else None,
            "评分": parse_number(r.get("score")),
            "主热度口径": r.get("primary_heat_metric"),
            "基线值": parse_number(r.get("baseline_value")),
            "基线日期": date_to_ms(r.get("baseline_date")),
            "D+3日期": date_to_ms(r.get("d3_date")),
            "D+3值": parse_number(r.get("d3_value")),
            "D+3来源": r.get("d3_source"),
            "结果": r.get("result") if r.get("result") in BACKTEST_RESULTS else None,
            "说明": r.get("reason"),
            "结论卡一句": r.get("card_line_zh"),
        }))
    return rows


def build_watchlist() -> list[dict]:
    cands = sorted(P.CONFIG_DIR.glob("watchlist-candidates-*.csv"))
    cands += sorted(P.CONFIG_DIR.glob("watchlist_candidates_*.csv"))
    cands += P.glob_many("watchlist-candidates-*.csv", "watchlist_candidates_*.csv")
    selected_mode = False
    if not cands and P.WATCHLIST.exists():
        cands = [P.WATCHLIST]
        selected_mode = True
    if not cands:
        return []
    path = cands[-1]
    rows = []
    for r in read_csv(path):
        platform = platform_label(r.get("platform"))
        handle = (r.get("handle") or "").strip()
        key = f"{platform or r.get('platform')}|{handle}"
        if selected_mode:
            chosen = str(r.get("selected") or "").strip().lower() in ("yes", "true", "1", "已选")
            status = "已选" if chosen else "候选"
        else:
            status = "候选"
        tag = r.get("followers_tag") if r.get("followers_tag") in VERIFY_TAGS else None
        rows.append(fields_clean({
            "去重键": key,
            "状态": status,
            "排序": parse_number(r.get("rank")),
            "平台": platform,
            "handle": handle,
            "主页链接": r.get("profile_url") if (r.get("profile_url") or "").startswith("http") else None,
            "类型": r.get("type"),
            "显示名": r.get("display_name"),
            "粉丝数": parse_number(r.get("followers")),
            "粉丝统计日": date_to_ms(r.get("followers_as_of")),
            "粉丝来源": r.get("followers_source"),
            "粉丝标签": tag,
            "视频数": parse_number(r.get("video_count")),
            "开号日期": date_to_ms(r.get("account_created")),
            "更新频率": r.get("posting_frequency"),
            "早发证据梗": r.get("evidence_meme"),
            "证据日期": r.get("evidence_date"),
            "证据链接": r.get("evidence_link"),
            "证据说明": r.get("evidence_note"),
            "语言": r.get("language"),
            "地区": r.get("region"),
            "地区来源": r.get("region_source"),
            "推荐理由": r.get("why"),
            "注意": r.get("caveats"),
            "主页核对": r.get("profile_spotcheck"),
            "简介": r.get("bio"),
        }))
    return rows


def build_digest_index() -> list[dict]:
    """Hard-coded only for links we actually have. Do not invent verdicts for older versions."""
    # v5 verdicts come from the seeded tracker
    tracker = P.TRACKER
    by_verdict = {"做": [], "观望": [], "不做": []}
    if tracker.exists():
        for r in read_csv(tracker):
            if r.get("date") == "2026-11-10" and r.get("verdict") in by_verdict:
                by_verdict[r["verdict"]].append(r.get("meme"))
    items = [
        {
            "date": "2026-11-10",
            "version": "v5",
            "url": "https://rlarkus1gkty4r86.usttp.larksuite.com/wiki/T9G7wtF29i3pOpkuwxdumICntCW",
            "do": "、".join(by_verdict["做"]),
            "watch": "、".join(by_verdict["观望"]),
            "dont": "、".join(by_verdict["不做"]),
            "note": "现行结构版：总排名表 + 每梗七块 + Top100 话题 + 7日/30日曲线。",
        },
        {
            "date": "2026-11-10",
            "version": "v4",
            "url": "https://rlarkus1gkty4r86.usttp.larksuite.com/wiki/VTYkw3syziAUTZkG3tMucmmrtge",
            "do": "",
            "watch": "",
            "dont": "",
            "note": "结构被否决的上一版。当时的做/观望/不做名单没有单独保存，这里只记链接，不补结论。",
        },
    ]
    rows = []
    for it in items:
        key = f"{it['date']}|{it['version']}"
        rows.append(fields_clean({
            "去重键": key,
            "日期": date_to_ms(it["date"]),
            "版本": it["version"],
            "Lark链接": it["url"],
            "做的梗": it["do"],
            "观望的梗": it["watch"],
            "不做的梗": it["dont"],
            "备注": it["note"],
        }))
    return rows


BUILDERS = {
    "cc_rank_snapshot": lambda as_of, tag_ids: build_cc_rank_snapshot(as_of, tag_ids),
    "cc_hashtag_curve": lambda as_of, tag_ids: build_cc_hashtag_curve(as_of, tag_ids),
    "cc_hashtag_audience": lambda as_of, tag_ids: build_cc_hashtag_audience(as_of, tag_ids),
    "meme_daily_tracker": lambda as_of, tag_ids: build_meme_daily_tracker(),
    "remix_videos": lambda as_of, tag_ids: build_remix_videos(as_of),
    "backtest": lambda as_of, tag_ids: build_backtest(),
    "watchlist": lambda as_of, tag_ids: build_watchlist(),
    "digest_index": lambda as_of, tag_ids: build_digest_index(),
}


def write_batches(as_of: str, existing_keys: dict[str, set[str]] | None = None) -> dict:
    tag_ids = load_tag_ids(as_of)
    out_dir = BATCH_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    def dest(name: str) -> Path:
        return out_dir / f"{as_of}-{name}"
    summary = {}
    for key, builder in BUILDERS.items():
        records = builder(as_of, tag_ids)
        skipped = 0
        updates = []
        known = existing_keys.get(key) if existing_keys else None
        id_map = known if isinstance(known, dict) else None
        if known:
            keep = []
            for rec in records:
                dk = rec.get("去重键")
                if dk and dk in known:
                    if id_map and key in {"meme_daily_tracker", "backtest", "digest_index"}:
                        updates.append({
                            "record_id": id_map[dk],
                            "fields": {k: v for k, v in rec.items() if k != "去重键"},
                        })
                    skipped += 1
                    continue
                keep.append(rec)
            records = keep
        payload_records = [{"fields": rec} for rec in records]
        if updates:
            dest(f"{key}.update.json").write_text(
                json.dumps(updates, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        # write chunked files and a combined file
        combined = {
            "table_key": key,
            "table_name": TABLES[key]["name"],
            "dedupe_field": "去重键",
            "as_of": as_of,
            "count": len(payload_records),
            "skipped_existing": skipped,
            "records": payload_records,
        }
        dest(f"{key}.json").write_text(
            json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        chunks = list(chunk(payload_records))
        compact_n = 40
        compact_files = []
        for i, ch in enumerate(chunks, 1):
            chunk_path = dest(f"{key}.part{i:02d}.json")
            chunk_path.write_text(
                json.dumps({
                    "table_key": key,
                    "table_name": TABLES[key]["name"],
                    "part": i,
                    "parts": len(chunks),
                    "count": len(ch),
                    "records": ch,
                }, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            recs_path = dest(f"{key}.part{i:02d}.records.json")
            recs_path.write_text(
                json.dumps(ch, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            for j in range(0, len(ch), compact_n):
                sub = ch[j : j + compact_n]
                si = j // compact_n + 1
                spath = dest(f"{key}.part{i:02d}.s{si:02d}.json")
                # sanitize near-integer floats for cleaner Lark Number fields
                def _clean(obj):
                    if isinstance(obj, float):
                        r = round(obj)
                        if abs(obj - r) < 1e-6:
                            return int(r)
                        return round(obj, 2)
                    if isinstance(obj, list):
                        return [_clean(x) for x in obj]
                    if isinstance(obj, dict):
                        return {k: _clean(v) for k, v in obj.items()}
                    return obj
                sub = _clean(sub)
                spath.write_text(
                    json.dumps(sub, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                compact_files.append(spath.name)
        summary[key] = {
            "table_name": TABLES[key]["name"],
            "built": combined["count"] + skipped,
            "to_upload": len(payload_records),
            "skipped_existing": skipped,
            "updates": len(updates),
            "parts": len(chunks),
            "compact_files": compact_files,
        }
        print(f"{TABLES[key]['name']:10} built={summary[key]['built']:4} upload={summary[key]['to_upload']:4} skipped={skipped} parts={len(chunks)}")
    dest("summary.json").write_text(
        json.dumps({"as_of": as_of, "tables": summary}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def load_existing_keys(path: Path) -> dict:
    """Accept {table: [去重键, ...]} or {table: {去重键: record_id}}."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            out[key] = {str(dedupe): record_id for dedupe, record_id in value.items()}
        else:
            out[key] = set(value)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Build Lark Base batches. Off unless --sync-lark.")
    p.add_argument("--as-of", default="2026-11-10")
    p.add_argument(
        "--existing-keys",
        help="JSON {table: [去重键]} to skip, or {table: {去重键: record_id}} to update tracker, backtest, and digest rows",
    )
    p.add_argument("--schema-only", action="store_true")
    P.add_lark_flags(p)
    args = p.parse_args()
    if args.schema_only:
        print(json.dumps({k: v["name"] for k, v in TABLES.items()}, ensure_ascii=False, indent=2))
        return 0
    if not P.lark_enabled(args.sync_lark, args.no_lark):
        print(P.lark_disabled_message())
        return 0
    existing = load_existing_keys(Path(args.existing_keys)) if args.existing_keys else None
    write_batches(args.as_of, existing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
