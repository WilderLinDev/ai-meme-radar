# Daily AI video meme digest — routine prompt

Write in Chinese. Purpose: decide which meme to build an AI template for TODAY. As detailed as possible; length is fine. Accuracy over speed: delivery any time in the morning is fine. Priority platforms: TikTok first, then CapCut templates, then Instagram Reels; also X, YouTube Shorts, Reddit etc. as supporting sources; never Douyin. Window: last 24-48h (Monday covers the weekend). Never invent posts, links or numbers; tag each number 【已核实】/【第三方读数】/【估算】; never interpolate; show gaps and say plainly when no 30-day series exists. Three pain points to fix every run: 漏梗 (coverage), 数据口径不一 (consistency), 做不做判断不靠谱 (judgment).

Efficiency rule: pull every bulk dataset ONCE at the start of the run into files, then do all meme matching and analysis from those files. Never re-pull a Top 100 list per meme. Completeness rule: capture as much data as each page shows (all dimensions, not just the ones the report uses) so it can be analysed later.

Where files go: this git repo, flat month folder `reports/YYYY-MM/`, every file prefixed with the report date. Examples for 2026-11-10 live in `reports/2026-11/`:

- `2026-11-10-daily-report.md` and `2026-11-10-daily-report.docx`
- `2026-11-10-meme-pack.json`
- `2026-11-10-heat.json` and `2026-11-10-heat.csv` (meme,date,metric,value,source,complete)
- `2026-11-10-remix-stats.csv`
- `2026-11-10-cc-top100.csv` (all regions combined) and, when saved per region, `2026-11-10-cc-top100-us.csv` (region code lowercase)
- `2026-11-10-cc-hashtag-trends.csv` and `2026-11-10-cc-hashtag-detail.json`
- `2026-11-10-watchlist-posts.csv`
- charts directly in the same folder: `2026-11-10-heat-<slug>.png`, `2026-11-10-cc-trend-<slug>.png`

No `reports/YYYY/MM/`, no per-day folder, no `charts/` subdirectory. Cumulative tracker and backtest stay in `data/`, not in the month folder.

Paths such as `/workspace/lark` and `/workspace/tiktok_cc` are the old runtime locations. Scripts still read them if those directories exist, but new files are written with the names above.

Research (organize BY MEME, never split by platform):

- Coverage watchlist: all accounts in `config/watchlist.csv` (53 as of 2026-11-10: 43 TikTok + 10 Instagram template / AI-effect / repost / trend accounts across US, GB, DE, JP, FR and others). TikTok/IG profile grids are not readable by fetch, so check them in the box browser (computerUse, batched dispatches after the CC list pull, e.g. 2 dispatches of ~25 accounts): for each account open the profile and record every post from the last 48h (post link, date, caption, views/likes shown, which meme/format, whether it's a CapCut template or AI effect) into `reports/YYYY-MM/YYYY-MM-DD-watchlist-posts.csv`. Any format appearing on 2+ watchlist accounts is a candidate meme even if absent elsewhere. Note accounts that couldn't be opened (Instagram may need login; say so, don't sign in). Also CapCut template pages/usage counts.
- Heat: X get_posts_counts_recent (7 days, UTC days), ViralRemix daily boards https://viralremix.org/tiktok-trends/YYYY-MM-DD, Know Your Meme, jumponthetrend, MakeViral, Turnly, CapCut pages, remix posting dates. Save `reports/YYYY-MM/YYYY-MM-DD-heat.json` and `.csv`.
- TikTok Creative Center bulk pull (box browser logged in; computerUse, one at a time, start this first): 16 lists = 8 regions (US, GB, AU, CA, DE, JP, KR, FR; NL is not offered by CC — its page redirects to US, so skip it and note it) × period 7 and 30, Industry = News & Entertainment, Top 100 each, from https://ads.tiktok.com/creative/creativeCenter/trends/hashtag?region=<CC>&period=7|30. Tell the subagent to read the rows from the data the page has already loaded rather than scrolling row by row where possible, and to save every field each row has (rank, rank change/new flag, hashtag, posts, views, industry, detail id, region). Write one combined file `reports/YYYY-MM/YYYY-MM-DD-cc-top100.csv`. Per-region files, when kept, are `reports/YYYY-MM/YYYY-MM-DD-cc-top100-<region>.csv` with the region in lowercase (`us`, `gb`, …). (Took ~28 min on 2026-11-10.) rank_change was blank on 11/10, so NEW/fade is a 7d-vs-30d proxy; say so.
- Then filter that file locally (no browser) to candidate tags that fit as memes / AI-template opportunities; don't pad with generic tags. Detail pages only for those candidates (pattern /creative/creativeCenter/trends/hashtag/<id>?region=<CC>&period=30 and 7; detail ids are the same across regions), in ONE batched computerUse dispatch, capturing EVERYTHING the detail page shows: daily popularity curve 7d and 30d, window totals (posts, views), audience age distribution, audience top countries (popularity index, not %), and any related videos (only cover VideoIDs are exposed). Interests/related hashtags/creators were not shown on 11/10; record as missing if still absent. Reuse curves already captured on previous days (`*-cc-hashtag-trends.csv` in older month folders, or Lark Base if sync is on): for a tag already curved, only extend with new days, but still refresh audience data. Save `reports/YYYY-MM/YYYY-MM-DD-cc-hashtag-trends.csv` (curves, with region) and `reports/YYYY-MM/YYYY-MM-DD-cc-hashtag-detail.json` (all other dimensions). If login expired, say so in one line.
- TikTok Top100 tags (any region) that fit as memes or AI-template opportunities become their OWN scored meme sections, tagged 【TikTok Top100·<regions>】 (multi-region = stronger signal; use the audience age/region data in the analysis). Exclude political/election, LIVE/official-incentive, adult, unlicensed IP/celebrity likeness, brand-unsafe, not-video-gen tags (reasons briefly inside related sections; no standalone CC section, no 200-tag table).
- 二创分享率: for each meme, 5-10 highest-view REMIX videos (not the original) across platforms -> `reports/YYYY-MM/YYYY-MM-DD-remix-stats.csv` (meme, link, platform, creator, date, views, likes, shares, comments, saves, is_AI). Refresh counts in the browser when they can't be fetched. Median and view-weighted share rate; n<5 = 样本不足 after trying other platforms.
- Lifecycle (every meme): 起火日期, 已火天数, 高峰状态 (上升中/接近峰值/峰值/回落 x% from peak with peak date) from 7d and 30d data (CC curves, X, ViralRemix, remix dates, history tracker). Trailing zeros = gaps.
- Early signals: 2-5 just-starting candidates (watchlist accounts, X AI video creators, AI model accounts Seedance/Kling/Veo/Sora/Hailuo/PixVerse, Reddit r/aivideo, newly rising CC tags).

Consistency: append the day's memes to `data/meme-daily-tracker.csv` with `python scripts/update_tracker.py` (same canonical meme id and same metrics every day; primary heat metric per meme kept fixed day to day). Use the tracker for day-over-day movement and longer curves.

Backtest (judgment check): run `python scripts/backtest.py`. Each meme recommended 做 on day D counts as 对 if its primary heat metric is still rising at D+3, else 错, or 数据不足. Output defaults to `data/backtest-latest.json` and `data/backtest-latest.csv`. Show it in two places: a short 回测 subsection right after the 总排名 table (hit rate to date, each recent 做 pick's result), and one line in each affected meme's 结论卡. If hit rate is poor, say which sub-score misled and adjust judgment accordingly (state the adjustment).

Scoring: 100 points = 热度/趋势/分享率/竞争/窗口, 20 each (趋势 and 窗口 driven by lifecycle; missing data scored conservatively). Verdict 做 (~>=65, 窗口>=10, no IP/format veto) / 观望 / 不做. Full rubric: `docs/scoring.md`.

Report structure (three parts; NO 往期回查, 行动清单, appendix, standalone CC section):

一、总排名: one table — 排名, 梗 (each linking to its section), 综合评分 (with 5 sub-scores), 结论, 窗口期, 已火天数, 高峰状态; then the 回测 subsection.

二、逐个梗详解: one section per meme ordered by score (观望/不做 also full; their 怎么做 framed as 如果要做), seven blocks in order: 1 结论卡 (verdict, score/100 with 5 items, window, 起火日期/已火天数/是否仍在高峰, movement vs previous digest, backtest line, one-line reason); 2 是什么 + 链接; 3 热度曲线 (7d/30d charts, current position, peak, regions, audience age where known); 4 二创分享率 (merged cross-platform table with links); 5 竞争与模板 (CapCut usage, one-click sites, watchlist accounts that posted it); 6 怎么做, detailed enough to start immediately (模板玩法, 用户输入, AI工具和提示词, BGM, 标题标签); 7 风险.

三、早期信号: each a section with the same seven blocks.

Build with:

```
python scripts/build_report.py \
  --date YYYY-MM-DD \
  --pack reports/YYYY-MM/YYYY-MM-DD-meme-pack.json
```

Optional inputs: `--md`, `--cc-csv`, `--remix-csv`, `--heat-json`, `--cc-trends-csv`, `--backtest-json`. Defaults write `reports/YYYY-MM/YYYY-MM-DD-daily-report.docx` and date-prefixed PNGs in that same month folder. Font default is `assets/fonts/NotoSansSC-Regular.otf` (not bundled). `reportlib` (charts and the docx theme) is not in this repo; point `paths.reportlib` in `config/settings.yaml` at it, or leave it on `/workspace/lark` when that directory exists. The 2026-11-10 pack at `reports/2026-11/2026-11-10-meme-pack.json` is the sample.

Save the report into this GitHub repo under `reports/YYYY-MM/` by default. Commit the markdown, the meme pack, the csv/json snapshots, and the charts. That is the delivery archive.

Lark is optional and off by default (`sync_lark: false` in `config/settings.example.yaml`). Do not import the Word file to Lark Wiki and do not append rows to the Lark Base 「AI视频梗数据库」 unless this run is explicitly enabled with `--sync-lark` or `sync_lark: true` in `config/settings.yaml`.

When Lark sync is enabled:

- Wiki import (computerUse): open https://rlarkus1gkty4r86.usttp.larksuite.com/wiki/Myv8w0Hsfi1a4fkkE4AuBEa1tHd (Personal Hub › Work & Projects › Grok Bot), hover its tree row, import the `.docx` as a Lark doc. Create nothing else, delete nothing. If Lark login expired or import fails, say so in one line and still deliver the repo files.
- Base append: schema and table ids are in `config/lark-base-schema.json` (base id `KakJbMCKNaHiaws7u2ZuqNfIttg`, which is the base URL identifier, not an app secret). Run `python scripts/sync_lark.py --as-of YYYY-MM-DD --sync-lark` (with `--existing-keys` from search_records) to make batches under `data/lark-batches/`, then create_records with inlined arrays (batches of ~40–80). Use `python scripts/sync_lark_delta.py --sync-lark` when the base already has rows and the run must create plus update. Append the day's rows to every table: CC榜单快照 (all regions × 7/30d), CC话题曲线, CC话题受众 (age/country), 梗每日追踪, 二创视频, 回测 (update results that became judgeable), 监控账号 (状态 field; all 53 are 已选; 去重键 {平台}|{handle}), 日报索引 (去重键 date|version, date, Lark doc link, 做/观望/不做 lists, run time). Add a table if new dimensions appear (e.g. a 监控账号帖子 table for watchlist-post rows). Never duplicate dedupe keys; verify counts with search_records. If a write fails, say so in one line. No app secret is stored in this repo; the user Lark connector is the only write path.

Deliver in this chat: the top picks (做) with score, 已火天数 and 高峰状态, backtest hit rate in one line, the 不做 list in one line, the repo path of the report (and the Lark doc link only if sync was on), one line on rows added to the Base if sync was on, total run time, and 1-2 key chart images. If genuinely nothing new is trending, send a one-line note saying so and still save the files under `reports/`.
