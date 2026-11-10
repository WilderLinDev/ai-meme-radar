#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build reports/YYYY-MM/YYYY-MM-DD-meme-pack.json from the base pack plus later evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import paths as P

DAY = "2026-11-10"
V5_PATH = P.resolve(DAY, "meme-pack-base.json", "meme_pack_2026-11-10.json")
HEAT_PATH = P.resolve(DAY, "heat.json", "heat_2026-11-10_run2.json", "heat_2026-11-10.json")
DETAIL_PATH = P.resolve(DAY, "cc-hashtag-detail.json", "cc_hashtag_detail_2026-11-10.json")
OUT_PATH = P.dated(DAY, "meme-pack.json")

# Five equal 0–20 dimensions. Totals must equal the sum.
# Movement is vs the 11/10 v5 pack, using today's 8-region lists, recaptured
# curves (end 11/7), ViralRemix 11/9 complete + 11/10 incomplete snapshot,
# and Turnly 11/10. Incomplete days are never used for peak math.

SCORES = {
    "Cat on Ultra Bee": {
        "scores": {"热度": 11, "趋势": 15, "分享率": 19, "竞争": 16, "窗口": 15, "total": 76},
        "verdict": "做",
        "window": "约 4–6 天，仍适合和宠物页一起上",
        "reason": "分享率仍是今天最高（TikTok 中位约 3.8%，n=6）【已核实】，Turnly 近 7 日 73 个创作者、Hot this week 第 2【第三方读数】。热度分从 12 收到 11：没有 ViralRemix 日产量，X 为 0，按「Turnly 50+」档计，不再往上抬。",
        "score_notes": {
            "热度": "无 ViralRemix 日榜、X 完整日为 0【已核实】；Turnly 近 7 日 73 个创作者（50+档，8–11）【第三方读数】",
            "趋势": "无全站日曲线，不假设在涨；Turnly 仍热、二创发布 11/6–11/8、已火仅 5 天，给 15，低于 v5 的 17",
            "分享率": "TikTok 中位约 3.77%（n=6）【已核实】，样本未刷新，沿用今日早先核实值",
            "竞争": "CapCut 宠物骑车模板有用量，但音频/话题体量更大，缺口仍在",
            "窗口": "原片 11/5，已火 5 天，约 4–6 天窗口仍成立",
        },
        "days_hot_short": "5 天",
        "peak_status_short": "上升中（无日榜）",
    },
    "Shaking Head": {
        "scores": {"热度": 9, "趋势": 17, "分享率": 16, "竞争": 17, "窗口": 12, "total": 71},
        "verdict": "做",
        "window": "作为宠物页配菜，不要当唯一赌注",
        "reason": "二创分享率仅次于 Cat on Ultra Bee（中位 2.18%），ViralRemix 完整日 11/9 以 486 创新高、仍标 Rising；11/10 未满日快照 381，方向没有反转。适合和猫骑车放在同一页。",
        "score_notes": {
            "热度": "ViralRemix 完整日最高 486（日产量几百档，4–7；因已上日榜且在涨，给 9）【第三方读数】",
            "趋势": "完整日 11/4 的 80 → 11/9 的 486（窗口最高）；11/10 快照 381 仍标 Rising，complete=false，不参与峰值计算",
            "分享率": "TikTok 中位 2.18%【已核实】，样本未刷新",
            "竞争": "未核实到铺开的主模板，玩法简单、护城河浅",
            "窗口": "作为宠物页第二个按钮，不要单独压主研发",
        },
        "days_hot_short": "约 22 天",
        "peak_status_short": "上升中",
    },
    "#lastchristmas": {
        "scores": {"热度": 16, "趋势": 13, "分享率": 6, "竞争": 14, "窗口": 18, "total": 67},
        "verdict": "做",
        "window": "从现在到圣诞节前，约数周",
        "reason": "8 区 News & Entertainment 榜里，它是少数同时停在多区 7 日榜、又适合照片生成短片的非政治话题：DE 第 9、GB 第 17、US 第 68（7 日），30 日 US 第 65、GB 第 76。【第三方读数】30 日指数接近峰值（回落 5.8%），但新抓到的 7 日曲线 11/7 从 100 掉到 52.5，要盯着看。季节窗口仍有数周。",
        "score_notes": {
            "热度": "CC 美国 7 日 4.7K 帖 / 27.8M 播放，且 7 日已出现在 DE/GB/US 三区（DE 第 9 最高）【第三方读数】，从 v5 的 15 提到 16",
            "趋势": "30 日指数峰值 11/6 的 100 → 11/7 的 94.2，回落 5.8%（接近峰值）；同日 7 日指数从 100 落到 52.5（回落 47.5%，两套指数不能横比）。曲线止于 11/7，此次已重抓。趋势从 14 收到 13，不把 7 日末日急跌当成 30 日破位",
            "分享率": "没有足够高播二创样本，保守分 6",
            "竞争": "未核实到只做这个情绪的专用模板；用户自制剪辑是主要竞争",
            "窗口": "圣诞节前还有数周，18 分保留",
        },
        "days_hot": 21,
        "days_hot_label": "本轮 CC 30 日指数约从 10/21 持续越过约 20，已火 21 天（10/21→11/10，含首日）【已核实·CC相对指数】",
        "days_hot_short": "约 21 天",
        "peak_status": "30 日接近峰值，回落 5.8%（11/6 的 100 → 11/7 的 94.2）；7 日窗口同日从 100 落到 52.5。曲线止于 11/7，不是报告日。【已核实·CC相对指数】",
        "peak_status_short": "30日接近峰值；7日末日急跌",
        "ignite_date": "本轮 CC 30 日指数从 10/21 起持续上升（10/17 曾短暂越过约 20）",
        "source_tag": "【TikTok Top100·DE,GB,US】",
    },
    "Shoulder Carry": {
        "scores": {"热度": 16, "趋势": 10, "分享率": 10, "竞争": 18, "窗口": 12, "total": 66},
        "verdict": "做",
        "window": "约 3–5 天",
        "reason": "音频使用量与 CapCut 模板的缺口仍是今天最大的产品切口，但 ViralRemix 只有 11/9 一个完整日点（27.6K 第 2），11/10 未满日快照掉到 10.7K、站方标 Past peak（complete=false，不能用来定高峰）。热度、趋势和窗口都比对 v5 更保守，总分从 80 收到 66，结论仍是做，不要按昨天的 80 分去压主研发。",
        "score_notes": {
            "热度": "ViralRemix 11/9 完整日 27,600（20–40K 档，16–17）【第三方读数】；11/10 未满日快照 10,700，不用于给分",
            "趋势": "完整日点只有 1 个，不能判仍在上升，也不能确认已过高峰；11/10 未满日急跌只作为风险信号。从 v5 的 18 收到 10",
            "分享率": "TikTok 中位 0.84%（n=10）【已核实】，中等，样本未刷新",
            "竞争": "CapCut「Cause I'm The One」11/6 用量 5,397，仍远低于音频条数，缺口最大",
            "窗口": "因日榜后出现急跌信号，从约 5–7 天下调到约 3–5 天（12 分）",
        },
        "days_hot_short": "AI波约 21 天",
        "peak_status": "日榜出现后大幅下滑，完整日点不足，还不能定高峰。ViralRemix 11/9 才进日榜（27.6K）；11/10 快照 10.7K、▼61%、站方标 Past peak，但该日未完，不参与峰值计算。【第三方读数】",
        "peak_status_short": "日榜后急跌，未确认高峰",
    },
    "Can I Ride": {
        "scores": {"热度": 16, "趋势": 13, "分享率": 6, "竞争": 18, "窗口": 12, "total": 65},
        "verdict": "做",
        "window": "约 3–5 天",
        "reason": "ViralRemix 完整日 11/8 峰值 24.8K、11/9 仍有 24.3K（回落约 2%，Rising）；11/10 未满日快照 15.4K，站方仍标 Rising，但相对峰值已低约 38%，日未完不能定转折。分享率样本仍不足。总分从 72 收到 65，窗口收短，结论仍是做。",
        "score_notes": {
            "热度": "ViralRemix 11/9 完整日 24,300（20–40K 档）【第三方读数】；11/10 快照 15,400 未满日，不用来降到 12–15 档",
            "趋势": "完整日相对峰值只回落约 2%，仍接近峰值；11/10 未满日偏低，从 v5 的 16 收到 13",
            "分享率": "样本不足或分享率偏低，保守分 6，样本未刷新",
            "竞争": "CapCut 用量相对音频/话题仍有缺口",
            "窗口": "从「上升段尽快上」下调到约 3–5 天（12 分）",
        },
        "days_hot_short": "32 天",
        "peak_status": "接近峰值或刚过 11/8 高点。ViralRemix 完整日峰值 11/8 的 24.8K → 11/9 的 24.3K（−2%，Rising）；11/10 快照 15.4K 仍标 Rising，complete=false。【第三方读数】",
        "peak_status_short": "接近峰值或刚过",
    },
    "Bicep Heart": {
        "scores": {"热度": 16, "趋势": 7, "分享率": 15, "竞争": 12, "窗口": 8, "total": 58},
        "verdict": "观望",
        "window": "约 2–3 天，先看会不会再掉",
        "reason": "X 完整日从 11/4 的 17,138 降到 11/9 的 13,809（回落 19.4%）【已核实】，ViralRemix 11/9 12K Peak、11/10 快照 10K 仍标 Peak。分享率还不错，但趋势在回落，先观望。五项分数与 v5 相同。",
        "score_notes": {
            "热度": "X 完整日 11/4–11/9 合计约 9.6 万（接近 10 万档下沿）；ViralRemix 完整日 12K（5–20K 档）。按讨论体量给 16",
            "趋势": "X 完整日回落 19.4%（15–40% 档，4–7），给 7",
            "分享率": "TikTok 中位约 2%+【已核实】，样本未刷新",
            "竞争": "已有若干模板/站点，中等",
            "窗口": "还在回落，约 2–3 天",
        },
        "days_hot_short": "11 天",
        "peak_status_short": "回落 19.4%",
    },
    "Then I Walk In": {
        "scores": {"热度": 8, "趋势": 15, "分享率": 10, "竞争": 16, "窗口": 8, "total": 57},
        "verdict": "观望",
        "window": "先观察 48 小时，适合轻量试水",
        "reason": "ViralRemix 完整可见点 11/9 的 152 为窗口最高，11/10 快照 116 仍标 Rising，但 11/5–11/7 缺页。体量还小，维持观望。分数与 v5 相同。",
        "score_notes": {
            "热度": "ViralRemix 完整日最高 152（日产量几百档），给 8【第三方读数】",
            "趋势": "可见完整日在涨，但有缺口，给 15",
            "分享率": "中等，样本未刷新",
            "竞争": "模板尚未铺开",
            "窗口": "先观察 48 小时",
        },
        "days_hot_short": "约 23 天",
        "peak_status_short": "上升中（有缺口）",
    },
    "Ba Ba Ba Dance": {
        "scores": {"热度": 20, "趋势": 13, "分享率": 5, "竞争": 11, "窗口": 6, "total": 55},
        "verdict": "观望",
        "window": "只适合维持已有能力，不要新开主模板",
        "reason": "ViralRemix 仍第 1，完整日 11/9 为 46.7K（相对 11/2 峰值 53.4K 回落 13%），11/10 快照 38.3K 标 Peak。绝对热度最高，但分享率低、模板竞争已经在，维持观望。分数与 v5 相同。",
        "score_notes": {
            "热度": "ViralRemix 完整日 46,700（≥40K 档）【第三方读数】",
            "趋势": "完整日回落 13%，接近峰值（12–15），给 13；11/10 快照标 Peak，日未完",
            "分享率": "偏低，给 5，样本未刷新",
            "竞争": "多站和模板都在做，中等偏低",
            "窗口": "只适合维持已有能力",
        },
        "days_hot_short": "39 天",
        "peak_status_short": "接近峰值，回落 13%",
    },
    "冬日恐悚 / 悬疑反转": {
        "scores": {"热度": 13, "趋势": 3, "分享率": 6, "竞争": 15, "窗口": 12, "total": 49},
        "verdict": "观望",
        "window": "作为常青能力保留，不要追官方标签",
        "reason": "8 区 7 日榜已全部看不到这两条官方比赛标签（FADE_30D 代理）。30 日仍很高：恐怖赛 US 第 1、DE 第 6、GB 第 21；悬疑赛 US 第 4。此次重抓后，恐怖赛 30 日指数 11/7 为 50.9（回落 49.1%），悬疑赛补到 11/7 的 75.5（回落 24.5%，此前曲线只到 11/6）。趋势按「已离开 7 日榜」收到 3 分。不要追标签，冬日反转能力可以留着。",
        "score_notes": {
            "热度": "30 日体量仍大（恐怖赛 US 370.2K 帖 / 2.2B 播放）【第三方读数】，但 7 日已全部出局，从 14 收到 13",
            "趋势": "已离开全部 8 区 Creative Center 7 日榜（退潮档 0–3）；此次重抓悬疑赛曲线补到 11/7，回落从 20% 修正为 24.5%。从 v5 的 5 收到 3",
            "分享率": "没有足够二创样本，保守分 6",
            "竞争": "官方比赛本身会分流，但「冬日反转短片」产品切口还在",
            "窗口": "作为常青能力，从 14 收到 12",
        },
        "days_hot": 31,
        "days_hot_label": "恐怖比赛约从 10/10 起火，已火 31 天；悬疑比赛约从 10/20 起火，已火 21 天。两条标签都已离开 7 日榜。【已核实·CC相对指数】",
        "days_hot_short": "约 31 天",
        "peak_status": "已离开全部 8 区 7 日榜。恐怖赛 30 日指数峰值 10/19 的 100 → 11/7 的 50.9，回落 49.1%；悬疑赛峰值 10/26 的 100 → 11/7 的 75.5，回落 24.5%（此次重抓补上 11/7；该条曲线只有 10/19–11/7）。【已核实·CC相对指数】",
        "peak_status_short": "已离7日榜，回落49%/25%",
        "source_tag": "【TikTok Top100·US,DE,GB】",
    },
    "Flamingo Float": {
        "scores": {"热度": 11, "趋势": 8, "分享率": 9, "竞争": 9, "窗口": 8, "total": 45},
        "verdict": "观望",
        "window": "约 2–3 天，先看会不会离开模板站热榜",
        "reason": "Turnly 近 7 日 82 个创作者、Hot this week 第 1【第三方读数】，但没有 ViralRemix 日榜，二创样本发布仍集中在 11/3–11/5。按口径把热度从 15 收到 11（Turnly 50+档），趋势按「没有可用日曲线给 8」处理。窗口仍按 2–3 天观察给 8 分。总分 45，压在观望下沿。",
        "score_notes": {
            "热度": "无 VR 日榜；Turnly 82 个创作者（50+档 8–11），给 11。不把第三方累计播放估计当当日体量",
            "趋势": "没有可用日曲线，按口径给 8，不假设在涨。从 v5 的 10 收到 8",
            "分享率": "中等偏低，样本未刷新",
            "竞争": "已有模板和站点",
            "窗口": "约 2–3 天或先观察，给 8（v5 是 6）",
        },
        "days_hot_short": "8 天",
        "peak_status_short": "高峰或平台期（无日榜）",
    },
    "Turning My Mom Into Me": {
        "scores": {"热度": 7, "趋势": 10, "分享率": 6, "竞争": 8, "窗口": 7, "total": 38},
        "verdict": "观望",
        "window": "先观察 48 小时",
        "reason": "ViralRemix 11/9 完整可见点 135 仍是可见最高，但 11/10 已跌出 Top 50（未上榜≠0）。趋势从 14 收到 10，总分 38，因是回潮/早期格式仍记观望，不按 45 分硬切成不做。",
        "score_notes": {
            "热度": "可见完整日最高 135，给 7【第三方读数】",
            "趋势": "曾在涨，但有缺口，且 11/10 跌出 Top 50，从 14 收到 10",
            "分享率": "样本不足，保守分 6",
            "竞争": "已有类似变老/变年轻模板",
            "窗口": "先观察 48 小时",
        },
        "days_hot_short": "约 10 天",
        "peak_status_short": "有缺口；11/10跌出日榜",
    },
    "#imsosorry": {
        "scores": {"热度": 11, "趋势": 3, "分享率": 6, "竞争": 11, "窗口": 5, "total": 36},
        "verdict": "不做",
        "window": "只适合文案变体或维持已有能力",
        "reason": "8 区确认已离开全部 7 日榜，只留在 30 日（GB 第 14、US 第 54、AU/CA 靠后）。30 日指数峰值 10/20 的 100 → 11/7 的 56.0，回落 44%。趋势按退潮给 3。总分 36，结论从观望改为不做。",
        "score_notes": {
            "热度": "30 日仍有体量（US 25.3K 帖 / 172.6M 播放；GB 第 14）【第三方读数】，从 12 收到 11",
            "趋势": "已离开全部 8 区 7 日榜，且 30 日回落 44%，给 3",
            "分享率": "没有足够样本，保守分 6",
            "竞争": "中等",
            "窗口": "只适合维持已有能力",
        },
        "days_hot_short": "25 天",
        "peak_status": "已离开全部 8 区 7 日榜。30 日指数峰值 10/20 的 100 → 11/7 的 56.0，回落 44%。【已核实·CC相对指数】",
        "peak_status_short": "回落 44%，已离7日榜",
        "source_tag": "【TikTok Top100·GB,US,AU,CA】",
    },
    "#damehombro": {
        "scores": {"热度": 11, "趋势": 3, "分享率": 6, "竞争": 10, "窗口": 5, "total": 35},
        "verdict": "不做",
        "window": "只适合维持已有能力",
        "reason": "8 区里只出现在美国 30 日第 12，已离开全部 7 日榜。30 日指数峰值 10/23 的 100 → 11/7 的 70.0，回落 30%。趋势按退潮给 3。总分 35，结论从观望改为不做。",
        "score_notes": {
            "热度": "仅 US 30 日第 12（21.2K 帖 / 71.6M 播放）【第三方读数】",
            "趋势": "已离开全部 8 区 7 日榜，给 3（v5 给了 6）",
            "分享率": "没有足够样本，保守分 6",
            "竞争": "中等",
            "窗口": "只适合维持已有能力",
        },
        "days_hot_short": "31 天",
        "peak_status": "已离开全部 8 区 7 日榜。30 日指数峰值 10/23 的 100 → 11/7 的 70.0，回落 30%。【已核实·CC相对指数】",
        "peak_status_short": "回落 30%，已离7日榜",
        "source_tag": "【TikTok Top100·US】",
    },
    "Malfoid": {
        "scores": {"热度": 18, "趋势": 3, "分享率": 10, "竞争": 2, "窗口": 1, "total": 34},
        "verdict": "不做",
        "window": "窗口已关闭，不应做成产品",
        "reason": "X 讨论体量仍大，但完整日从 11/4 的 66,729 降到 11/9 的 32,996（回落 50.6%）【已核实】。本质是手绘同人，不是照片生成短片。分数与 v5 相同。",
        "score_notes": {
            "热度": "X 完整日仍高（11/9 为 32,996；7 日合计约 26 万）【已核实】，按讨论体量给 18",
            "趋势": "回落 50.6%，超过 40%，给 3",
            "分享率": "X 转发不能与 TikTok 分享横比，中等分 10",
            "竞争": "不是可产品化的视频格式，给 2",
            "窗口": "不应做成产品，给 1",
        },
        "days_hot_short": "约 49 天",
        "peak_status_short": "回落 50.6%",
    },
    "Grandpa Fish": {
        "scores": {"热度": 10, "趋势": 9, "分享率": 7, "竞争": 4, "窗口": 3, "total": 33},
        "verdict": "不做",
        "window": "只适合维持已有能力",
        "reason": "Turnly 近 7 日只有 26 个创作者（不到 50+档）【第三方读数】，CapCut 已经铺开。热度从 13 收到 10。结论仍是不做。",
        "score_notes": {
            "热度": "无 VR 日榜；Turnly 26 个创作者，低于 50+档，从 13 收到 10",
            "趋势": "无日曲线，二创发布已过集中窗口，给 9",
            "分享率": "中等偏低，样本未刷新",
            "竞争": "CapCut 已经铺开，给 4",
            "窗口": "只适合维持已有能力",
        },
        "days_hot_short": "6 天",
        "peak_status_short": "高峰附近（无日榜）",
    },
    "#halloweentransition": {
        "scores": {"热度": 10, "趋势": 1, "分享率": 6, "竞争": 8, "窗口": 2, "total": 27},
        "verdict": "不做",
        "window": "季节已结束",
        "reason": "仍出现在 5 个地区的 30 日榜，但已离开全部 7 日榜。30 日指数 11/6 最后非零点 7.4，11/7 为 0。季节结束，热度从 13 收到 10。",
        "score_notes": {
            "热度": "5 区 30 日残留（US 第 22，35.9K 帖 / 169.1M 播放）【第三方读数】，从 13 收到 10",
            "趋势": "11/7 已是 0，季节结束，给 1",
            "分享率": "没有足够样本，保守分 6",
            "竞争": "节日变装模板很多",
            "窗口": "已关闭",
        },
        "days_hot_short": "32 天",
        "peak_status": "季节已结束。30 日指数峰值 10/30 的 100 → 11/6 最后非零点 7.4，11/7 为 0（按缺口处理）。已离开全部 8 区 7 日榜。【已核实·CC相对指数】",
        "peak_status_short": "季节结束，11/7 为 0",
        "source_tag": "【TikTok Top100·US,CA,AU,GB,DE】",
    },
}

# applied after copy; heat_position / heat_sources pulled from heat json when present


import json
from pathlib import Path

NEW_MEMES_PATH = P.resolve(DAY, "new-memes.json", "new_memes_run2.json")


def attach_audience(meme, details):
    tags = [t.lstrip("#").lower() for t in (meme.get("cc_hashtags") or [])]
    if meme["name"].startswith("#"):
        tags.append(meme["name"].lstrip("#").lower())
    tags = list(dict.fromkeys(tags))
    rows = []
    for d in details:
        slug = d["hashtag"].lstrip("#").lower()
        if slug in tags:
            rows.append({
                "hashtag": d["hashtag"] if d["hashtag"].startswith("#") else "#"+d["hashtag"],
                "region": d.get("region"),
                "period_days": d.get("period_days"),
                "posts": d.get("posts"),
                "views": d.get("views"),
                "age": d.get("age") or [],
                "countries": d.get("regions") or [],
                "countries_metric": (d.get("other") or {}).get("regions_metric") or "popularity index (not %)",
                "url": d.get("url"),
            })
    if rows:
        meme["cc_audience"] = rows
    return meme


def attach_heat(meme, heat):
    entry = (heat.get("memes") or {}).get(meme["name"])
    if not entry:
        return meme
    # Prefer pack-authored peak/ignite when we recaptured curves; else use heat file.
    if entry.get("position") and not meme.get("heat_position_override"):
        # For recaptured CC memes we already wrote a better heat_position in SCORES/new memes.
        if not meme.get("heat_position"):
            meme["heat_position"] = entry["position"]
    if entry.get("sources") and not meme.get("heat_sources"):
        srcs = entry["sources"]
        if isinstance(srcs, list):
            meme["heat_sources"] = [s if isinstance(s, str) else json.dumps(s, ensure_ascii=False) for s in srcs]
        else:
            meme["heat_sources"] = [str(srcs)]
    if entry.get("gaps") and not meme.get("heat_gaps"):
        g = entry["gaps"]
        meme["heat_gaps"] = g if isinstance(g, str) else "；".join(str(x) for x in g)
    return meme


def apply_overlay(meme, overlay):
    for k, v in overlay.items():
        if k == "score_notes" and isinstance(v, dict) and isinstance(meme.get("score_notes"), dict):
            notes = dict(meme["score_notes"])
            notes.update(v)
            meme["score_notes"] = notes
        else:
            meme[k] = v
    return meme


def movement_row(name, old, new):
    old_s = (old or {}).get("scores") or {}
    new_s = new["scores"]
    old_t = old_s.get("total")
    delta = None if old_t is None else int(new_s["total"]) - int(old_t)
    old_v = (old or {}).get("verdict")
    new_v = new["verdict"]
    if old is None:
        change = "新进"
    elif old_v != new_v:
        change = f"{old_v}→{new_v}"
    else:
        change = f"仍为{new_v}"
    return {
        "name": name,
        "v5_total": old_t,
        "v6_total": new_s["total"],
        "delta": delta,
        "v5_verdict": old_v,
        "v6_verdict": new_v,
        "verdict_change": change,
        "v5_scores": old_s or None,
        "v6_scores": new_s,
    }


def main():
    pack = json.loads(V5_PATH.read_text(encoding="utf-8"))
    heat = json.loads(HEAT_PATH.read_text(encoding="utf-8"))
    details = json.loads(DETAIL_PATH.read_text(encoding="utf-8"))
    new_memes = json.loads(NEW_MEMES_PATH.read_text(encoding="utf-8"))

    v5_by = {m["name"]: m for m in pack["memes"]}
    out_memes = []
    changes = []

    for m in pack["memes"]:
        nm = copy.deepcopy(m)
        ov = SCORES.get(m["name"])
        if ov:
            apply_overlay(nm, ov)
        # patch lastchristmas origin / reason already in overlay; also origin text
        if nm["name"] == "#lastchristmas":
            nm["origin"] = (
                "歌曲 1984；TikTok 上每年圣诞季回流。今日它同时停在 Creative Center "
                "News & Entertainment 近 7 日榜的德国第 9、英国第 17、美国第 68，"
                "以及近 30 日榜的美国第 65、英国第 76，是 8 区榜里少数仍适合做成照片生成短片的非政治话题。"
                "NL 页会跳到美国，没有独立荷兰榜。【第三方读数】"
            )
            nm["heat_position"] = (
                "30 日相对指数峰值 11/6 的 100 → 11/7 的 94.2，回落 5.8%；"
                "此次重抓补上美国 7 日曲线，同日从 100 落到 52.5（回落 47.5%，两套指数不能横比）。"
                "曲线最后一天是 11/7，不是报告日。7 日榜：DE 第 9、GB 第 17、US 第 68。【已核实·CC相对指数】"
            )
            nm["heat_gaps"] = (
                "曲线止于 11/7；没有足够高播二创分享率样本；Creative Center 详情页未展示兴趣/相关话题/创作者，相关视频只有内部 VideoID、没有公开链接。"
            )
        if nm["name"] == "冬日恐悚 / 悬疑反转":
            nm["heat_position"] = (
                "两条官方标签都已离开全部 8 区 7 日榜。恐怖比赛 30 日指数峰值 10/19 的 100 → 11/7 的 50.9，回落 49.1%；"
                "悬疑比赛此次重抓后曲线为 10/19–11/7，峰值 10/26 的 100 → 11/7 的 75.5，回落 24.5%。"
                "30 日仍在榜：恐怖赛 US 第 1 / DE 第 6 / GB 第 21，悬疑赛 US 第 4。【已核实·CC相对指数】"
            )
            nm["heat_gaps"] = "悬疑比赛 30 日曲线只有 10/19–11/7，没有更早的点。详情页未展示兴趣/相关话题/创作者。"
        if nm["name"] == "Shoulder Carry":
            nm["heat_position"] = (
                "日榜出现后立刻大幅下滑，但还不能判死峰值。"
                "ViralRemix 11/9 才首次进入 Top 50（27.6K 第 2，Tracking）；"
                "11/10 快照 10.7K 第 3、▼61%、站方标 Past peak。11/10 为 02:24 UTC 早盘快照，complete=false，不参与峰值计算。【第三方读数】"
            )
        attach_heat(nm, heat)
        attach_audience(nm, details)
        nm["v5_scores"] = (v5_by[m["name"]].get("scores") or {})
        nm["v5_verdict"] = v5_by[m["name"]].get("verdict")
        ch = movement_row(m["name"], v5_by[m["name"]], nm)
        nm["score_delta"] = ch["delta"]
        nm["verdict_change"] = ch["verdict_change"]
        changes.append(ch)
        # validate totals
        s = nm["scores"]
        calc = sum(int(s[k]) for k in ("热度", "趋势", "分享率", "竞争", "窗口"))
        if calc != int(s["total"]):
            raise SystemExit(f"{nm['name']} total {s['total']} != {calc}")
        out_memes.append(nm)

    for nm in new_memes:
        attach_heat(nm, heat)
        attach_audience(nm, details)
        nm["v5_scores"] = None
        nm["v5_verdict"] = None
        nm["score_delta"] = None
        nm["verdict_change"] = "新进"
        ch = movement_row(nm["name"], None, nm)
        changes.append(ch)
        s = nm["scores"]
        calc = sum(int(s[k]) for k in ("热度", "趋势", "分享率", "竞争", "窗口"))
        if calc != int(s["total"]):
            raise SystemExit(f"{nm['name']} total {s['total']} != {calc}")
        out_memes.append(nm)

    pack["report_date"] = "2026-11-10"
    pack["version"] = "v6"
    pack["run"] = "run2"
    pack["title_note"] = "11/10 v6（新流程试跑）"
    pack["memes"] = out_memes
    pack["changes_vs_v5"] = changes
    pack["cc_coverage"] = {
        "regions_requested": ["US", "GB", "AU", "CA", "DE", "JP", "KR", "FR", "NL"],
        "regions_available": ["US", "GB", "AU", "CA", "DE", "JP", "KR", "FR"],
        "nl_note": "Creative Center 荷兰页会跳到美国，没有独立 NL 榜。本 run 实际是 8 区。",
        "rank_change": "8 区 Top100 的 rank_change 字段全部为空；NEW / fade 用同一地区 7 日榜 vs 30 日榜是否出现作为代理（NEW_7D / FADE_30D / SUSTAIN）。",
        "curves_end": "2026-11-07",
        "thriller_curve": "悬疑比赛 30 日曲线只有 2026-10-19 至 2026-11-07。",
        "audience_note": "年龄为百分比（18-24 / 25-34 / ≥35）；国家/地区是 popularity index，不是占比。详情页未展示兴趣、相关话题和创作者；相关视频只有内部封面 VideoID，没有公开 URL。",
    }
    pack["backtest"] = {
        "horizon_days": 3,
        "rule_zh": "报告日 D 评为「做」的梗，若 D+3 的主热度完整日点严格高于 D 当天记下的基线，记为对；完整日点小于等于基线记为错；没有可用基线或没有完整 D+3 点记为数据不足。",
        "first_judgment_date": "2026-11-13",
        "note_zh": "今天是新流程的第一天正式打「做」。D+3 要到 2026-11-13 才有首批对/错判断。在此之前回测结果都是数据不足，不能用来修正今天的名单。",
    }
    pack["early_signals_meta"] = heat.get("early_signals") or []
    pack["watchlist_note"] = (
        "尚未选出正式 watchlist.csv，本 run 用 watchlist_candidates_2026-11-10.csv。"
        "28 个候选账号里，只有少数能从第三方页读到最近发帖日，没有一个格式在 48 小时内被 2 个以上账号同时确认。"
    )
    pack["gaps"] = [
        "荷兰 Creative Center 页跳转到美国，9 区实际只有 8 区。",
        "Top100 的 rank_change 全部为空，NEW/fade 只是 7 日 vs 30 日是否上榜的代理。",
        "CC 曲线最后一天是 2026-11-07，不是报告日；悬疑比赛曲线只有 10/19–11/7。",
        "详情页没有兴趣、相关话题、创作者；相关视频没有公开链接，只有内部 VideoID。国家/地区是人气指数，不是百分比。",
        "ViralRemix 11/10 看板在晚间重抓时仍盖着 02:24 UTC 的戳，只能当未满日快照，不参与峰值计算。",
        "本 run 没有浏览器，未能打开 TikTok/Instagram 监控号格子、也未能刷新二创播放和分享数、未能复核 CapCut 用量。二创样本沿用今日早先已核实行。",
        "正式监控账号尚未圈选，watchlist.csv 不存在。",
        "回测的首批对/错判断要到 2026-11-13 才出现。",
        "X 没有 30 日归档计数；Google Trends 未重试。",
    ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    ranked = sorted(out_memes, key=lambda m: (-m["scores"]["total"], m["name"]))
    print("WROTE", OUT_PATH, "memes", len(out_memes))
    print(f"{'Rk':>2} {'Score':>5} {'Ver':<4} {'Δ':>4} {'Days':>8} {'Peak':<22} Name")
    for i, m in enumerate(ranked, 1):
        s = m["scores"]
        d = m.get("score_delta")
        ds = "—" if d is None else f"{d:+d}"
        print(f"{i:2d} {s['total']:5d} {m['verdict']:<4} {ds:>4} {str(m.get('days_hot_short') or '—'):>8} {str(m.get('peak_status_short') or '')[:22]:<22} {m['name']}")

    print("\nVERDICT CHANGES:")
    for c in changes:
        if c["verdict_change"] not in ("仍为做", "仍为观望", "仍为不做"):
            print(" ", c["name"], c["verdict_change"], "score", c["v5_total"], "→", c["v6_total"])


if __name__ == "__main__":
    main()
