# AI meme radar

Daily overseas AI-meme video radar. Decide which meme is worth an AI template today. Platform order is TikTok, then CapCut templates, then Instagram Reels. Supporting sources are X, YouTube Shorts, and Reddit. Never Douyin.

This file is the entry point for any coding agent. The research procedure is `docs/routine-prompt.md`. Scoring is `docs/scoring.md`.

## Repo map

- `docs/` — routine prompt, schedule, scoring, data dictionary
- `scripts/` — tracker, backtest, report builder, Lark batch builder, `check_setup.py`
- `scripts/reportlib/` — charts and the Word theme (`docx_report.py`)
- `config/watchlist.csv` — default 53 public TikTok and Instagram accounts
- `config/settings.example.yaml` and `config/.env.example` — empty templates
- `config/lark-base-schema.json` — Base fields and dedupe keys, no account ids
- `research/` — optional Google Ads Keyword Planner
- `reports/YYYY-MM/` — date-prefixed daily files (`2026-11-10-daily-report.md`)
- `data/` — cumulative tracker and backtest
- Real ids and secrets live in `~/.config/ai-meme-radar/` (`AMR_CONFIG_DIR` overrides it)

## Honesty

Never invent posts, links, or numbers. Tag each number 【已核实】, 【第三方读数】, or 【估算】. Do not interpolate. Leave gaps and say when a series is missing. Scores in the meme pack must add up. The report builder does not invent scores.

## Scope is fixed

Do not ask the user about regions, platforms, watchlist accounts, or language. Use the defaults as they are:

- Creative Center regions: US, GB, AU, CA, DE, JP, KR, FR. Periods 7 and 30. Industry News & Entertainment. NL is not offered; skip it and say so.
- Platforms: TikTok, then CapCut, then Instagram Reels.
- Watchlist: every row in `config/watchlist.csv`.
- Report language: Chinese.

## Preflight

Before a daily run, run:

```bash
python scripts/check_setup.py
```

Read its Present, Ask, and Skipped sections. Ask only for a login, secret, or setting that the script puts under Ask, or that a live pull then rejects. Say what that item unlocks and which step you will skip without it. Then continue. Items under Skipped are optional: note them and do not ask.

## Minimum path

Lark and Google Ads are optional. With neither one configured, the pipeline still writes `reports/YYYY-MM/YYYY-MM-DD-daily-report.md` and `.docx`. Charts use a fallback font if `paths.font` is missing; Chinese glyphs in charts may be missing, and the doc says so.

## What each access unlocks

- X API — 7-day post counts (`get_posts_counts_recent`). Not stored in this repo. If the tool is unauthorized, ask once. Without it, skip X heat points and record the gap.
- TikTok Creative Center, browser login — 8-region Top 100 and hashtag detail pages. If the browser is logged out, ask once. Without it, skip that bulk pull and say so.
- Instagram login — optional. Unlocks watchlist profile grids. Without it, skip Instagram rows and say so.
- Lark (`lark.enabled`, `lark.base_app_token`, `lark.wiki_parent_url`, `lark.tables.*`) — optional Wiki import and Base append. Off by default. If enabled but a required key is empty, ask for that key and skip Lark only.
- Google Ads (`google_ads.customer_id` plus `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN` in the local `.env`) — optional Keyword Planner. Skip `research/ads_keyword_*.py` when they are empty.
- `GITHUB_TOKEN` — optional. Push uses existing git credentials. Ask only if push fails for lack of auth.

## Daily run

1. `git pull` in the working copy.
2. `python scripts/check_setup.py`.
3. Pull bulk data once into `reports/YYYY-MM/YYYY-MM-DD-*` files. Match memes from those files. Details are in `docs/routine-prompt.md`.
4. `python scripts/update_tracker.py` then `python scripts/backtest.py`.
5. Write the digest markdown, then `python scripts/build_report.py --date YYYY-MM-DD --pack reports/YYYY-MM/YYYY-MM-DD-meme-pack.json`.
6. Commit and push the day's report files.
7. Run `python scripts/sync_lark.py --as-of YYYY-MM-DD` only when Lark is enabled. It writes batches under `data/lark-batches/` and refuses to run when required Lark ids are empty.
