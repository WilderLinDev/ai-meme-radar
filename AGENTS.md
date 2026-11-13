# AI Meme Radar

Trend discovery, market research and template-opportunity assessment for AI creative products. Daily output: a Chinese report of what changed and what to act on, plus an in-depth report per key opportunity.

**Before any task in this repository, read and follow `.agents/skills/ai-meme-radar/SKILL.md`.** It is the complete procedure: goals, research method, the daily workflow, Ge Fei API rules, SQLite, the Python / agent split, decisions, reports, Lark publishing, recovery and delivery.

Then, as needed:

1. `GLOSSARY.md` - the words this repo uses. Use them exactly.
2. `docs/research-method.md` - lifecycle, decision, priority, confidence, the seven dimensions, backtests.
3. `docs/adr/` - why the repo is shaped this way.

Entry point: `uv run python scripts/run_day.py run`. Tests: `uv run pytest`.

Honesty: never invent posts, links or numbers. Tag numbers in free text 【已核实】, 【第三方读数】 or 【估算】. Do not interpolate. Record what you could not get as a gap.

```
src/radar/          config, db (SQLite schema), text, decisions, backtest, lark, pipeline
src/radar/gefei/    catalog (live), client (recorded calls), sync (resumable), normalize
src/radar/research/ models (input schemas), ingest, discover, metrics
src/radar/reports/  daily, deep (Markdown)
scripts/run_day.py  the one entry point
config/             research.toml (creative vocabulary), watchlist.csv, settings.example.toml
tests/              pytest, with a fake Ge Fei built on the real catalog fixtures
```
