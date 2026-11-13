# AI meme radar

Daily overseas AI-meme video radar. One output: which meme is worth an AI template today (做 / 观望 / 不做). Read these in order:

1. `GLOSSARY.md`: the words this repo uses. Use them exactly.
2. `docs/runbook.md`: the daily procedure.
3. `docs/scoring.md`: the rubric, verdict rules, lifecycle and backtest.
4. `docs/adr/`: why the repo is shaped this way.

## Division of labour

You (the agent) collect raw snapshots in the browser and write judgments. Code does everything else. Never hand-write a number code can compute, and never edit `meme-pack.json`, `daily-report.*`, `data/tracker.csv` or `data/backtest.*` by hand: rebuild them.

```
uv run radar check                  preflight
uv run radar ingest   YYYY-MM-DD    validate data/raw/YYYY-MM-DD/
uv run radar scaffold YYYY-MM-DD    draft reports/YYYY-MM-DD/judgments.json
uv run radar build    YYYY-MM-DD    pack, tracker, backtest, md, docx, charts
uv run radar schema [file]          columns of every input file
```

## Honesty

Never invent posts, links or numbers. Tag numbers in free text 【已核实】, 【第三方读数】 or 【估算】. Do not interpolate. Record what you could not get in `gaps.json`. A verdict that differs from the score's suggestion needs `override_reason`.

## Scope is fixed

Do not ask about regions, platforms, watchlist accounts or language. Creative Center: US, GB, AU, CA, DE, JP, KR, FR × 7 and 30 days, News & Entertainment (NL is not offered; skip it and say so). Platforms: TikTok, then CapCut, then Instagram Reels; never Douyin. Watchlist: every selected row in `config/watchlist.csv`. Report language: Chinese.

Ask only for what `radar check` lists under Ask, or for a login or authorisation a live pull rejects: say what it unlocks and which step you skip without it, then continue. Lark is optional and off by default.

## Repo map

```
src/radar/         the package (cli, config, registry, raw, analysis, scoring, pack,
                   tracker, backtest, render, export)
tests/             pytest; tests/fixtures/2026-11-10 is the golden sample
scripts/           run_day.py (code stages with resume + reports/DAY/run-timing.json)
config/            watchlist.csv, lark-base.json, settings.example.toml
data/memes.csv     meme registry (identity, hashtags, primary heat metric)
data/raw/DAY/      raw snapshots, written once
data/tracker.csv   one row per meme per report day
data/backtest.*    latest backtest of every verdict
reports/DAY/       judgments.json (yours), meme-pack.json, daily-report.md/.docx, charts
```

Local settings live in `~/.config/ai-meme-radar/settings.toml` (`AMR_CONFIG_DIR` overrides). Nothing in the repo is secret.

## Changing code

`uv run pytest` must pass. Keep judgments out of code: no meme names, dates or scores in `src/`. A new raw source gets a schema in `src/radar/raw/schemas.py`; a new Lark field gets a `from` in `config/lark-base.json`.
