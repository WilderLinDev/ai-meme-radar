---
name: ai-meme-radar
description: Run or change AI Meme Radar, the daily trend-discovery and template-opportunity research system for AI creative products. Use for every task in this repository - the daily run, Ge Fei API research, writing research.json / assessments.json, human feedback, reports, Lark publishing, recovering an interrupted run, or changing the code.
---

# AI Meme Radar

AI Meme Radar finds internet trends early, works out the reusable content **format** behind each one, and decides which formats are worth turning into AI video, image or audio **template opportunities**. Every day it delivers one Chinese daily report focused on change and action, plus an in-depth report for each key opportunity.

Words in bold are defined in `GLOSSARY.md`; use them exactly. The decision framework is `docs/research-method.md`. Design decisions are in `docs/adr/`.

## Division of labour

| Python (deterministic) | You, the agent (judgment) |
| --- | --- |
| Ge Fei API calls, catalog, sync, checkpoints | discovering social trends in the browser |
| SQLite storage, normalization, dedupe | understanding memes and their formats |
| time series, change detection, lifecycle metrics | linking trends, formats, opportunities, keywords, sites |
| link suggestions, candidate grouping | analysing search demand and audience behaviour |
| backtests, report assembly, Lark publishing | investigating competitors and AI feasibility |
|  | final lifecycle, decision, priority, confidence, and why |

Never hand-write a number Python can compute. Never change how a deterministic metric is computed to fit a conclusion. Never edit `radar.db` or report files by hand; change the inputs and rerun.

## Fixed scope (do not ask)

- Markets: US primary; GB, CA, AU supplementary English markets; DE, JP, KR, FR observed; global (`WORLD`) for early signals.
- Social platforms: TikTok, CapCut, Instagram Reels, X, YouTube Shorts, Reddit. Never Douyin.
- TikTok Creative Center Top 100 is one source among many (US GB AU CA DE JP KR FR × 7/30 days, News & Entertainment; NL is not offered). It is not the candidate entry point.
- Watchlist: every `selected=yes` row of `config/watchlist.csv`.
- Report language: Chinese. Local Markdown is authoritative; Lark is the published copy.

Ask the user only for what preflight prints under `Ask:`, or for a login a live pull rejects: say what it unlocks and which step you skip without it, then continue.

## Where things are

- Code: this repo. Data: `~/ai-meme-radar-data/` (`$AMR_DATA_DIR` or `[paths] data_dir` override), outside Git:
  - `radar.db` - the only research store
  - `reports/daily/DAY.md`, `reports/opportunities/<id>/DAY.md`
  - `work/DAY/` - `candidates.json`, `assessments.draft.json` (Python) and `research.json`, `assessments.json` (you)
  - `feedback/*.json` - human feedback
- Settings: `~/.config/ai-meme-radar/settings.toml` (`$AMR_CONFIG_DIR`), template `config/settings.example.toml`. The Ge Fei token goes there or in `$GEFEI_API_TOKEN`, never in the repo.

## The one entry point

```bash
uv run python scripts/run_day.py run [DAY]            # every stage that can run; resumes
uv run python scripts/run_day.py call TOOL '{json}'   # one recorded Ge Fei call
uv run python scripts/run_day.py tools [GROUP]        # the live Ge Fei catalog
uv run python scripts/run_day.py status [DAY]         # stage log, sync retries, unsynced Lark docs
```

`run` exits 0 when the day is delivered, 2 when it is waiting for one of your files (it prints which), 1 on failure. Stages: preflight → sync → discover → research → scaffold → decide → backtest → report → publish. Sync and publish failures are recorded as gaps and do not stop the day.

## Daily procedure

DAY is today in Asia/Shanghai. Start: `git pull && uv sync && uv run python scripts/run_day.py run`.

### 1. Ge Fei sync (Python, automatic)

The first run pulls every accessible batch of emerging keywords, new-site launches, website discovery (with 28-day snapshots) and every revenue month (monthly and 28-day reports, all pages). Later runs pull only new batches, re-pull batches finished in the last `refresh_days` and the current/previous revenue month, and retry failed units. Locked data (`data_locked`) is recorded as a gap, not retried. Every response is stored raw in `api_calls`, normalized into snapshot tables, and costs nothing in credits.

### 2. Discover (Python writes `work/DAY/candidates.json`)

Read it first. It holds:
- `groups`: creative-relevant search / product / market candidates since the last run, merged when they share a keyword or domain, with `matches` to entities that already exist.
- `link_suggestions`: trend or opportunity search terms that match stored keywords or site titles.
- `refresh`: every live entity (not skipped) with the time of its last evidence. Refresh these.
- `query_hints`: entities with search terms but no search evidence in 7 days, with suggested calls. They are not executed; you decide.

### 3. Research (you, browser + Ge Fei queries)

Run the four channels in parallel in your head; any can surface a trend.

1. **Social**: sweep the watchlist accounts (last 48h), TikTok / CapCut template pages, Creative Center, Instagram Reels, X AI-video creators, YouTube Shorts, Reddit (r/aivideo and similar), model accounts (Seedance, Kling, Veo, Sora, Hailuo, PixVerse). Look for participation: remixes, templates used, duet/stitch counts, comment requests ("how do I make this"). Record what the page shows; never estimate a count you can read.
2. **Search**: social trend → its search terms → `keyword_volume` (US first, then GB/CA/AU), `google_trends`, `trends_rising`, `keyword_ideas`, `search_intent`, `serp` / `serp_review`, `keyword_difficulty`. Emerging keyword → find the social trend behind it. Not every early signal has search data; say so instead of forcing it.
3. **Product**: new launches / hosted sites in the creative space → which trend or keyword they serve; trend → who already sells it (`search_known_sites`, `domain_overview`, `site_keywords`, `site_history`, `domain_traffic`, `domain_dr`).
4. **Market**: revenue and traffic of competitors (`stripe_checkout_referrals`, `income_site_detail_v2`, `website_worth`, `backlink_value`, `domain_timeline`). Estimated traffic is not revenue; say which you have.

Go deeper on high-priority items: public internet, Know Your Meme, creator posts, template pages, competitor pricing. Use the knowledge base (`knowledge_search`, `knowledge_read`, `knowledge_ask`, `load_guide`) when Ge Fei's methodology helps; results are stored automatically.

**Ge Fei usage rules**
- Call through `run_day.py call` only, so every request, response, `requestId` and credit charge is recorded. Use MCP only for exploration you will not cite.
- Before calling, check `tools` for parameters and price. Batch keywords (up to 50 per `keyword_volume`). Identical calls within 7 days (30 for knowledge) are served from SQLite; pass `--fresh` only when you need new data and can say why.
- Do not run query APIs on every entity every day. Query when a candidate is new, when a decision depends on it, or when the last reading is stale for that decision.
- Cite a call with `"api_call_id"` on the evidence row. A value you cite must appear in that response; derived numbers are tagged 估算.

### 4. Write `work/DAY/research.json`

Schema: `src/radar/research/models.py` (`ResearchFile`). Ids are kebab-case and permanent. Before creating an entity, check `matches` and reuse the existing id; ingest rejects a new entity whose name or alias matches an existing one.

- `trends`: id, name, summary, aliases, `search_terms` (English queries a user would type), regions, platforms, origin.
- `formats`: the reusable pattern - what the user inputs, what they get.
- `opportunities`: what we could ship; `product_type` video / image / audio / effect / multi / other.
- `links`: trend -uses-> format, format -enables-> opportunity, trend -drives-> opportunity, trend -searched_as-> keyword, opportunity -targets-> keyword, any -competitor|related-> site, trend/format -related|variant_of-> same kind. Many-to-many is normal; never force one-to-one.
- `evidence`: one row per observation, with `channel`, `source`, `url`, `metric`, `value`, `unit`, `region`, `sample_size`, `metric_definition`, `collected_at` (with offset), `confidence`, `tag` (已核实 / 第三方读数 / 估算), optional `api_call_id`, and a `ref` (globally unique) so assessments can cite it. Qualitative evidence leaves `value` empty and explains in `note`. Keep metric names stable across days for the same series (`posts_24h`, `views_top10_remix`, `cc_index`, `search_volume`, ...): backtests follow them.
- `gaps`: everything you tried and could not get, with why. Missing is not zero; never interpolate.

Rerun. Fix every problem it lists, then rerun again.

### 5. Judge: copy `assessments.draft.json` to `assessments.json`

The draft lists every trend and opportunity that is new, has new evidence today, is key, or was never assessed, with read-only `facts` (series, keyword heat, links) and your last judgment. Delete entries you do not re-judge today; they keep their previous state and the report says so.

For each entry set four **independent** attributes and seven dimensions:
- `lifecycle`: early_signal / emerging / proven / fading
- `decision`: build / validate / monitor / skip
- `priority`: P0 / P1 / P2 / P3
- `confidence`: high / medium / low (how strong the evidence is, not how good the idea is)
- `dimensions`: social_momentum, search_demand, audience_participation, template_potential, ai_feasibility, competition (high = crowded), timing; each `level` high / medium / low / unknown, a `note` saying what it rests on, `evidence` refs (`e12` or `call:345`).
- `summary` (one line), `rationale`, `why_now`, `assumptions` (inferences and unvalidated assumptions, explicitly), `open_questions`, `next_steps` (required for build / validate).
- `tracked`: the one series backtests judge, fixed now: `{"kind": "evidence", "metric": ..., "region": ...}` or `{"kind": "keyword_heat", "keyword": ...}`. `expected_direction` defaults from lifecycle (rising / rising / holding / falling); override it if you mean something else.
- `deep`: for every **key opportunity** (build or validate, or P0 / P1) all twelve sections: trend_overview, why_now, social_evidence, search_demand, audience_behavior, format_analysis, product_opportunity, competition, ai_feasibility, recommendation, evidence_confidence, remaining_questions. Focus by lifecycle: early signals on discovery, initial evidence and potential; emerging on growth speed, spread and how to validate; proven on demand, competition and productization; fading on why it declines, the remaining window and what is reusable.

There is no overall score. Do not invent one in prose. Read `docs/research-method.md` before your first judgment and whenever a backtest result surprises you.

Rerun until the day exits 0.

### 6. Deliver

`run` writes `reports/daily/DAY.md` and the in-depth reports, then publishes them to Lark when enabled. Reply in chat with: the key opportunities (four attributes + one line each), new early signals, decision changes, the backtest line, gaps, credits spent today, local report paths and the Lark URLs (`status` lists any not synced). If nothing changed, say so in one line.

## Human feedback

People change decisions, priorities, lifecycle, links or research direction by dropping a JSON file into `<data>/feedback/` (schema `FeedbackFile`):

```json
{"feedback": [{"entity": "opportunity:baby-dance-template", "field": "priority", "value": "P1",
  "reason": "team capacity", "author": "name", "at": "2026-11-14T09:00:00+08:00"}]}
```

`field` is decision / priority / lifecycle / link_add / link_remove (`value` = `relation->kind:id`) / direction (free text guiding your next research). Each item is applied once. The agent's original assessment is never changed; the effective state shows both. The draft shows them under `facts.human_feedback`; act on research directions in your next sweep.

## Lark

Only finished reports go to Lark: one document per daily report, one document per key opportunity (overwritten with its latest in-depth report). Never upload the database, raw API data, batches, social data or intermediate files. Settings `[lark]`: `enabled`, `daily_parent` (Wiki node token), `opportunity_parent`, `identity`. Publishing uses `lark-cli docs +create/+update` with the user's login. A failure is a gap; the next run retries it and never creates a duplicate, because document ids live in `lark_docs`.

## Recovery

Rerun `run` with the same DAY. Finished sync units are skipped, failed ones retried; ingest is idempotent; unchanged reports are not rewritten or republished. `status DAY` shows the last event of every stage. If an input file is rejected, fix that file; never edit the database to get past a check.

## Changing code

`uv run pytest` must pass. Keep judgments out of `src/`: no trend names, dates or verdicts. The Ge Fei catalog is read live from `/api/v1/tools` and `/api/openapi.json`; never hand-maintain an endpoint list. A new normalized Ge Fei table belongs in `src/radar/gefei/normalize.py` with its DDL in `src/radar/db.py`.
