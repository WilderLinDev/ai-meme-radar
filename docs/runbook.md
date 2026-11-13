# Daily runbook

Every day at 08:30 Asia/Hong_Kong (cron `30 8 * * *`, ±15 min). Delivery any time in the morning is fine: accuracy over speed. The report is in Chinese and answers one question: **which meme is worth an AI template today.** Words in bold below are defined in `GLOSSARY.md`.

The scheduled Grok Bot job runs this Git checkout and its `radar` commands. Log the Git commit and start and finish times for CC lists, CC details, watchlist, heat and remixes, judgments, build, chat delivery, Git push, Wiki import and Base sync. Record interrupted stages and their last completed work so a retry can resume from the saved raw snapshots.

Window: the last 24–48h. Platforms: TikTok first, then CapCut templates, then Instagram Reels. X, YouTube Shorts and Reddit are supporting sources. Never Douyin.

## 0. Prepare

```bash
git pull
uv sync
uv run radar check
```

`uv run python scripts/run_day.py run $D` runs check, ingest, scaffold and build in order, reuses what is done (scaffold is skipped once `judgments.json` exists, build when its outputs are newer than its inputs) and appends every stage to `reports/$D/run-timing.json`. Log agent stages with `uv run python scripts/run_day.py mark $D <stage> start|done|failed --note "..."` (cc-lists, cc-details, watchlist, heat, remixes, judgments, chat, git-push, wiki, base-sync); `status $D` shows which raw snapshots exist and the last event of each stage.

Read Present / Ask / Skipped. Ask only for an item under Ask, or one that a live pull rejects, and say what it unlocks and which step you skip without it. Do not ask about scope.

Set `D=YYYY-MM-DD` (today, Asia/Shanghai). Everything collected today goes into `data/raw/$D/`. Run `uv run radar schema` for every file's columns.

## 1. Collect raw snapshots (agent, browser)

Pull each bulk dataset **once**, at the start, into files. Do all matching from the files afterwards. Save every field the page shows, even ones the report does not use. Never invent rows.

On retry, reuse completed raw snapshots. If a bulk source needs multiple passes, save each completed unit outside `data/raw/$D/` until the snapshot is ready to ingest. Resume unfinished units from that staging area. Record evidence that could not be collected in `gaps.json`.

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

Once `radar build` succeeds, reply in chat with the `make` picks, scores, days hot and peak status, the backtest line, the `skip` list, the report path, elapsed time and one or two chart images. If nothing new is trending, say so in one line and still commit.

```bash
git add data/memes.csv data/raw/$D data/tracker.csv data/backtest.* reports/$D
git commit -m "report: $D"
git push
```

If the push fails, attach the built Word report in chat and note that the Git push is pending. Retry the same report when Git access is restored.

## 7. Lark (only when `lark.enabled`)

Import `reports/$D/daily-report.docx` under `lark.wiki_parent_url`, store the doc URL under `[lark.digest_docs]` in local settings, and post the Wiki link in chat when ready. Run Base sync separately from chat delivery. The report index uses the stored Wiki URL.

Get existing keys first with the connector's `search_records` on each table's `去重键`. A list skips those rows, while a map of key to `record_id` also writes update batches (backtest rows change from pending to a result).

```bash
uv run radar export-lark $D --existing-keys data/lark-batches/$D/existing-keys.json
```

Call `create_records` / `update_records` with batches from the current export. Report Wiki or Base failures separately in chat.

Use the connector if the runtime lacks direct API authorization. For direct API writes, read each batch from file, reconcile existing records by `去重键` before retrying, and update changed records by `record_id`. Record batch sizes, elapsed time and API errors.
