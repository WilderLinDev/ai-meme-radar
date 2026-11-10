# Daily runbook

Every weekday at 08:30 Asia/Shanghai (cron `30 8 * * 1-5`, ±15 min). Delivery any time in the morning is fine: accuracy over speed. The report is in Chinese and answers one question: **which meme is worth an AI template today.** Words in bold below are defined in `GLOSSARY.md`.

Window: the last 24–48h (Monday covers the weekend). Platforms: TikTok first, then CapCut templates, then Instagram Reels. X, YouTube Shorts and Reddit are supporting sources. Never Douyin.

## 0. Prepare

```bash
git pull
uv sync
uv run radar check
```

Read Present / Ask / Skipped. Ask only for an item under Ask, or one that a live pull rejects, and say what it unlocks and which step you skip without it. Do not ask about scope.

Set `D=YYYY-MM-DD` (today, Asia/Shanghai). Everything collected today goes into `data/raw/$D/`. Run `uv run radar schema` for every file's columns.

## 1. Collect raw snapshots (agent, browser)

Pull each bulk dataset **once**, at the start, into files. Do all matching from the files afterwards. Save every field the page shows, even ones the report does not use. Never invent rows.

| File | What | How |
| --- | --- | --- |
| `cc-top100.csv` | Creative Center Top 100, 8 regions (US GB AU CA DE JP KR FR) × period 7 and 30, industry News & Entertainment. NL is not offered (it redirects to US): skip it. | Logged-in browser, start this first, one list at a time: `https://ads.tiktok.com/creative/creativeCenter/trends/hashtag?region=<CC>&period=7\|30`. Read rows from the data the page already loaded instead of scrolling. About 30 min. |
| `cc-curves.csv`, `cc-audience.csv` | Detail pages, **only for candidate hashtags**: daily curve 7d and 30d, audience age (pct), top countries (popularity index, not pct), interests if shown. | `…/trends/hashtag/<detail_id>?region=<CC>&period=30` and `7`. Detail ids are the same across regions. One batched pass. |
| `heat.csv` | Daily heat per meme: X `get_posts_counts_recent` (7 days, UTC days), ViralRemix daily boards (`https://viralremix.org/tiktok-trends/YYYY-MM-DD`), Turnly etc. Mark partial days `complete=false`. | API and fetch. |
| `remixes.csv` | 5–10 highest-view **remixes** per meme (never the original), across platforms: views, likes, shares, comments, saves, is_ai. | Refresh counts in the browser when fetch can't read them. |
| `watchlist-posts.csv` | Every post from the last 48h on each selected account in `config/watchlist.csv`: link, date, caption, views, meme, template or AI effect. | Browser, batched (~25 accounts per pass). Instagram may need login: skip and record a gap, never sign in. |
| `gaps.json` | Everything you could not get today and why: `[{"source": "...", "note": "..."}]`. | |

Leads worth chasing for early signals: formats on 2+ watchlist accounts, AI video creators on X, model accounts (Seedance, Kling, Veo, Sora, Hailuo, PixVerse), Reddit r/aivideo, newly rising CC tags, CapCut template pages.

## 2. Register memes

Every meme has a row in `data/memes.csv` before any file refers to it. Add new ones by hand:

- `id`: kebab-case, never changed later (`cat-ultra-bee`).
- `cc_hashtags`: `|`-separated, without `#`. A hashtag belongs to at most one meme.
- `primary_metric`: `viralremix_new_videos`, `x_posts`, `cc_index_30d` (needs `primary_region`), or `none`. Pick the series the backtest should judge, and keep it fixed.

A Top 100 hashtag that fits as a meme or AI-template opportunity is registered as its own meme. Everything else (politics and elections, LIVE or official incentives, adult, unlicensed IP or celebrity likeness, brand-unsafe, not video-generation) goes into `excluded_hashtags` in step 4, grouped by reason.

```bash
uv run radar ingest $D
```

It validates every raw file and every meme id and lists all problems at once. Fix and rerun until it is clean.

## 3. Scaffold

```bash
uv run radar scaffold $D
```

Writes `reports/$D/judgments.json`. Every candidate meme gets a draft with a read-only `facts` block (primary heat, peak status, share rate, Top 100 regions, watchlist accounts, movement since the last report, and rubric hints). Top 100 hashtags not yet linked or excluded appear in one `TODO` group under `excluded_hashtags`. Rerunning keeps what you have written and refreshes `facts`.

## 4. Judge (agent)

Fill each meme in `judgments.json`. Organise by meme, never by platform.

- `scores`: the five dimensions, 0–20 each, each with a `note`. Rubric: `docs/scoring.md`. Missing data scores conservatively.
- `verdict` plus `override_reason` when it differs from the suggested verdict.
- `reason` (one line), `window_note`, `ignite_date` and `ignite_note`, `part` (`main` or `early`).
- `what`, `origin`, `links`, `heat_note`, `share_note`, `competition`, `risks`.
- `howto` for every `make` meme, detailed enough to start immediately: template play, user input, AI tool and prompt, BGM, caption and hashtags.
- `watch_for` for `watch` memes: what would turn it into a `make`.
- `excluded_hashtags`: replace the TODO group with groups that each have a real reason.
- `notes`: run-level remarks, including how you adjusted after a poor backtest.

Tag every number in free text 【已核实】, 【第三方读数】 or 【估算】. Never interpolate. Say plainly when a series is missing.

## 5. Build

```bash
uv run radar build $D
```

Checks the judgments (registered ids, override reasons, every Top 100 hashtag accounted for), then writes `reports/$D/meme-pack.json`, `daily-report.md`, `daily-report.docx` and charts, updates `data/tracker.csv`, and reruns the backtest into `data/backtest.json` and `.csv`.

## 6. Deliver

```bash
git add data/memes.csv data/raw/$D data/tracker.csv data/backtest.* reports/$D
git commit -m "report: $D"
git push
```

Then reply in chat: the `make` picks with score, days hot and peak status; the backtest line; the `skip` list in one line; the report path; total run time; one or two chart images. If nothing new is trending, say so in one line and still commit.

## 7. Lark (only when `lark.enabled`)

```bash
uv run radar export-lark $D --existing-keys data/lark-batches/$D/existing-keys.json
```

Get existing keys first with the connector's `search_records` on each table's `去重键`: a list skips those rows, a map of key to record_id also writes update batches (backtest rows change from pending to a result). Then call `create_records` / `update_records` with each batch file inlined (40 records each). Import `reports/$D/daily-report.docx` under `lark.wiki_parent_url`, create nothing else, and store the doc URL under `[lark.digest_docs]` in local settings. If a write fails, say so in one line; the repo files are already delivered.
