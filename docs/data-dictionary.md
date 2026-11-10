# 数据字典

日报快照和累计表分开。日报一律在 `reports/YYYY-MM/`，文件名以 `YYYY-MM-DD-` 开头。累计表在 `data/`。

## 月份目录里的当天文件

| 文件 | 内容 |
| --- | --- |
| `YYYY-MM-DD-daily-report.md` | 当天日报正文 |
| `YYYY-MM-DD-daily-report.docx` | 同一份日报的 Word，供阅读，也可在开启 Lark 时导入 Wiki |
| `YYYY-MM-DD-meme-pack.json` | 每个梗的评分、结论、链接、做法。报告生成器的主输入 |
| `YYYY-MM-DD-heat.json` / `.csv` | 热度时间序列。列：meme, date, metric, value, source, complete |
| `YYYY-MM-DD-remix-stats.csv` | 高播二创，已排除原片。列含 meme, link, platform, creator, date, views, likes, shares, comments, saves, is_AI |
| `YYYY-MM-DD-cc-top100.csv` | 8 个地区 × 7 日和 30 日的 News & Entertainment Top 100，合并文件，行内带 region |
| `YYYY-MM-DD-cc-top100-<region>.csv` | 单地区榜。region 用小写，如 `us`、`gb`。旧文件名 `YYYY-MM-DD_US_NewsEnt_top100.csv` 仍能被脚本认出来 |
| `YYYY-MM-DD-cc-hashtag-trends.csv` | 话题详情页的 7 日 / 30 日相对指数曲线，带 region |
| `YYYY-MM-DD-cc-hashtag-detail.json` | 详情页上的其他维度：受众年龄、国家人气指数、相关视频 id |
| `YYYY-MM-DD-watchlist-posts.csv` | 53 个监控号近 48 小时的帖子 |
| `YYYY-MM-DD-heat-<slug>.png` | 该梗热度图 |
| `YYYY-MM-DD-cc-trend-<slug>.png` | 该话题的 7 日 + 30 日曲线图 |

`complete=false` 的热度点可以画出来，但不参与峰值和回落计算。缺日期留空，不插值。

Creative Center 的值是窗口内各自归一化的相对指数 0–100。7 日里的 100 和 30 日里的 100 不是同一个播放量。国家/地区是人气指数，不是百分比。

## data/ 累计文件

| 文件 | 内容 |
| --- | --- |
| `data/meme-daily-tracker.csv` | 一天一行、一个梗一行。去重键是日期 + 规范 ID。由 `scripts/update_tracker.py` 追加 |
| `data/backtest-latest.json` | D+3 回测结果，含 `summary_zh` 和每个梗的 `card_line_zh` |
| `data/backtest-latest.csv` | 同一份回测的表 |
| `data/lark-batches/` | 仅在 `--sync-lark` 时生成的 Base 批次。不入库 |

追踪表的主要列：date, meme, canonical_id, verdict, score, score_heat, score_trend, score_share, score_competition, score_window, primary_heat_metric, primary_heat_value, primary_heat_date, primary_heat_source，以及 X 7 日、ViralRemix、CC 排名/指数、二创中位分享率、起火日期、已火天数、高峰状态、窗口、part、source_tag、notes。

主热度口径一旦选定就固定：`viralremix_new_videos`、`x_posts`、`cc_index_30d`，或 `none_daily_volume`（没有可回测的日序列）。

## config/

`config/watchlist.csv` 是 53 个已选监控号。主要列：rank, platform, handle, profile_url, type, display_name, followers, followers_as_of, followers_tag, video_count, language, region, why, selected, selected_on。

`config/lark-base-schema.json` 只保留表、字段和去重键。Base app token、表 id、Wiki 链接都在本地 `lark.*` 设置里，不写进仓库。

表：

| 表 | 去重键 |
| --- | --- |
| CC榜单快照 | 抓取日期\|地区\|周期\|排名\|话题 |
| CC话题曲线 | 抓取日期\|话题\|地区\|周期\|日期 |
| CC话题受众 | 抓取日期\|话题\|地区\|周期\|维度\|分组 |
| 梗每日追踪 | 日期\|规范ID |
| 二创视频 | 日报日期\|链接 |
| 回测 | 推荐日\|规范ID |
| 监控账号 | 平台\|handle |
| 日报索引 | 日期\|版本 |

URL 字段必须是 `{link, text}`，不能是纯字符串。日期写成 Base 时区（America/Los_Angeles）当天 00:00 的毫秒时间戳。CC话题受众里，年龄用「占比」；国家用「人气指数」，不是百分比。同步脚本只有 `scripts/sync_lark.py`。

## 旧路径

数据目录默认是仓库里的 `data/` 和 `reports/`。本地 `paths.data_dir`、`paths.reports_dir` 可以改成别的路径。账号和密钥放在 `~/.config/ai-meme-radar/`。
