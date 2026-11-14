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
- Social platforms: TikTok, CapCut, Instagram Reels, X, YouTube Shorts. Never Douyin.
- TikTok Creative Center Top 100 is one source among many (US GB AU CA DE JP KR FR × 7/30 days, News & Entertainment; NL is not offered). It is not the candidate entry point.
- Watchlist: every `selected=yes` row of `config/watchlist.csv`.
- Report language: Chinese. Local Markdown is authoritative; Lark is the published copy.

Ask the user only to fix what the preflight report lists as FAILED (all items in one message). Record non-blocking access failures as research gaps. Only Creative Center may require a social login.

## Where things are

- Code: this repo. Data: `~/ai-meme-radar-data/` (`$AMR_DATA_DIR` or `[paths] data_dir` override), outside Git:
  - `radar.db` - the only research store
  - `reports/daily/DAY.md`, `reports/opportunities/<id>/DAY.md` (under `$AMR_REPORTS_DIR` / `[paths] reports_dir` if set)
  - `work/DAY/` - `candidates.json`, `assessments.draft.json` (Python) and `research.json`, `assessments.json` (you)
  - `feedback/*.json` - human feedback
- Settings: one loader (`src/radar/config.py`). Precedence: environment variables > `settings.toml` > defaults.
  - `settings.toml` is in `$AMR_CONFIG_DIR`, else `~/.config/ai-meme-radar/`. Template: `config/settings.example.toml`. Every key is optional.
  - Env vars: `GEFEI_API_TOKEN` (secret), `AMR_CONFIG_DIR`, `AMR_DATA_DIR`, `AMR_REPORTS_DIR`.
  - Required: the Ge Fei token, `[lark] daily_parent` (a Wiki node token; `opportunity_parent` optional) and a logged-in lark-cli `identity`. Publishing has no off switch.
  - Lark login is lark-cli's own (`lark-cli auth login`); the app stores no Lark credential.
  - Never ask the user to paste a secret into chat. They set it locally; you rerun.
  - Never paste the token into chat, files in the repo, commit messages or reports. Output is redacted, but don't rely on that.

## The one entry point

```bash
uv run python scripts/run_day.py run [DAY]            # strict preflight gate, then every stage; resumes
uv run python scripts/run_day.py call TOOL '{json}'   # one recorded Ge Fei call
uv run python scripts/run_day.py tools [GROUP]        # the live Ge Fei catalog
uv run python scripts/run_day.py status [DAY]         # stage log, sync retries, report path, every Lark doc + URL
```

`run` exits 0 when the day is delivered, 4 when preflight is NOT READY (nothing else ran), 2 when it is waiting for one of your files (it prints which), 1 on failure (input problems are listed all at once), 3 when another run already holds `<data>/run.lock`. Stages: preflight → sync → discover → research → scaffold → decide → backtest → report → publish. A sync or publish failure fails the run; rerun after fixing it and only the unfinished work is redone.

`status DAY` prints the last preflight result, the last event of every stage, sync units waiting for retry, the daily report path, and every Lark document as `[type] name | status | URL | local path | error`. Status is synced, stale (local report changed since publishing; the next `run` republishes), failed (with the reason) or unpublished (not published yet). `status`, `tools` and `call` don't take the lock.

## Daily procedure

DAY is today in Asia/Shanghai. Start: `git pull && uv sync`, then the gate.

### 0. Strict preflight (mandatory, before anything else)

Nothing starts until every required check passes. Every `run` rechecks everything; when a blocking check fails, the run stops with exit 4 and no other stage runs.

1. **Browser checks (you).** Use the connected browser and check each of these for real. A homepage that loads does not count: open the pages your research actually uses, using public access except for Creative Center.
   - `Browser connection`: the browser integration answers and can open a tab.
   - `Public web`: an ordinary public article page (for example Wikipedia or Know Your Meme) loads.
   - `TikTok`, `CapCut`, `Instagram`, `X`, `YouTube`: a hashtag, search, explore or template page on that site shows content. Check for a login wall, a CAPTCHA or a "content unavailable" page.
   - `Creative Center`: a Top 100 hashtag or popular page loads on ads.tiktok.com.
   - `Watchlist`: try at least one selected profile per platform in `config/watchlist.csv`. If only some open, report the check as failed with the accessible URLs and record partial coverage in the research file.
   Respect login walls, CAPTCHAs and access restrictions. Instagram, X and Watchlist failures are warnings, and login walls on other social platforms are also warnings. Only ask for a social login if Creative Center requires it. Write `work/DAY/preflight.browser.json`:
   ```json
   {"day": "DAY", "checked_at": "2026-11-14T08:05:00+08:00", "browser": "Claude in Chrome",
    "checks": [{"name": "TikTok", "status": "pass", "access": "logged_in",
                "urls": ["https://www.tiktok.com/tag/aibaby"], "result": "hashtag page lists videos"},
               {"name": "Instagram", "status": "failed", "access": "login_required", "urls": [],
                "result": "redirected to the login page", "reason": "not logged in",
                "fix": "log in to Instagram in the connected browser"}]}
   ```
   Include one entry per name above. `access` is logged_in, not_needed, login_required, blocked or unreachable. `urls` lists the research pages you actually opened. Python rejects a pass with no research page, a URL on the wrong site, a pass with a login wall, a Watchlist pass without a selected profile per platform, and a report from another day. Python never checks login state itself; your report is the only source.
2. **Python checks (`run`).** The same command checks the local environment (Python, dependencies, settings, environment variables, project config, watchlist, folders, disk, feedback files, SQLite schema and integrity, `uv`, the lock). It checks Ge Fei: the token, the endpoint and live catalog, authentication and balance via `GET /api/v1/me`, and free page-1 calls for data-service access. It checks Lark read-only: `lark-cli` runs, `auth status --verify` for the identity, each destination Wiki node exists with edit permission, `docs +create/+update` are available, and every document due for an update is still editable. No research credits are spent and nothing is written to Lark.
3. **One report.** `run` prints every check as PASS, WARN or FAILED with what it saw, the reason and the fix, and saves it to `work/DAY/preflight.json`. READY if there are no blocking failures.
4. **If NOT READY:** send the user one message listing every FAILED item and exactly what to do. Credentials are set locally, never pasted into chat. Then stop and wait. Do not start research, run `call`, write `research.json`, or ask about items one by one.
5. **When the user says it's fixed:** redo the browser checks that failed and rewrite `preflight.browser.json`, then rerun `run`. If the gate is READY, the workflow continues without asking for confirmation. If anything still fails, go back to step 4.

### 1. Ge Fei sync (Python, automatic)

The first run pulls every accessible batch of emerging keywords, new-site launches, website discovery (with 28-day snapshots) and every revenue month (monthly and 28-day reports, all pages). Later runs pull only new batches, re-pull batches finished in the last `refresh_days` and the current/previous revenue month, and retry failed units. A batch that is individually locked (`data_locked`) is recorded as a gap, not retried; a failed unit fails the run and is retried on the next run. Every response is stored raw in `api_calls`, normalized into snapshot tables, and costs nothing in credits.

### 2. Discover (Python writes `work/DAY/candidates.json`)

Read it first. It holds:
- `groups`: creative-relevant search / product / market candidates since the last run, merged when they share a keyword or domain (transitively), with `matches` to entities that already exist. Each item and group carries `discovery`: `vocabulary` (matched a creative term) or `unmatched_exploration` (up to 10 fresh Ge Fei keywords that matched nothing; `exploration: true` on the group). Look at exploration groups quickly: most are noise, a few are memes the vocabulary doesn't know yet. They are built from data already synced and cost no API calls.
- `stats`: total / included / truncated per source (search_vocabulary, search_exploration, launches, hosted, market). Large truncation means look at the source directly.
- `link_suggestions`: trend or opportunity search terms that match stored keywords or site titles.
- `refresh`: every live entity (not skipped) with the time of its last evidence. Refresh these.
- `query_hints`: entities with search terms but no search evidence in 7 days, with suggested calls. They are not executed; you decide.

### 3. Research (you, browser + Ge Fei queries)

Run the four channels in parallel in your head; any can surface a trend.

1. **Social**: sweep the watchlist accounts (last 48h), TikTok / CapCut template pages, Creative Center, Instagram Reels, X AI-video creators, YouTube Shorts, model accounts (Seedance, Kling, Veo, Sora, Hailuo, PixVerse). Look for participation: remixes, templates used, duet/stitch counts, comment requests ("how do I make this"). Record what the page shows; never estimate a count you can read.
2. **Search**: social trend → its search terms → `keyword_volume` (US first, then GB/CA/AU), `google_trends`, `trends_rising`, `keyword_ideas`, `search_intent`, `serp` / `serp_review`, `keyword_difficulty`. Emerging keyword → find the social trend behind it. Not every early signal has search data; say so instead of forcing it.
3. **Product**: new launches / hosted sites in the creative space → which trend or keyword they serve; trend → who already sells it (`search_known_sites`, `domain_overview`, `site_keywords`, `site_history`, `domain_traffic`, `domain_dr`).
4. **Market**: revenue and traffic of competitors (`stripe_checkout_referrals`, `income_site_detail_v2`, `website_worth`, `backlink_value`, `domain_timeline`). Estimated traffic is not revenue; say which you have.

Go deeper on high-priority items: public internet, Know Your Meme, creator posts, template pages, competitor pricing. Use the knowledge base (`knowledge_search`, `knowledge_read`, `knowledge_ask`, `load_guide`) when Ge Fei's methodology helps; results are stored automatically.

**Ge Fei usage rules**
- Call through `run_day.py call` only, so every request, response, `requestId` and credit charge is recorded. Use MCP only for exploration you will not cite.
- Before calling, check `tools` for parameters and price. If API credits are exhausted or unknown, use the free data services and public evidence. If a paid call returns quota or day_cap, stop paid calls for the run and record a gap. Batch keywords (up to 50 per `keyword_volume`). Identical calls within 7 days (30 for knowledge) are served from SQLite; pass `--fresh` only when you need new data and can say why.
- Do not run query APIs on every entity every day. Query when a candidate is new, when a decision depends on it, or when the last reading is stale for that decision.
- Cite a call with `"api_call_id"` on the evidence row. A value you cite must appear in that response; derived numbers are tagged 估算.

### 4. Write `work/DAY/research.json`

Schema: `src/radar/research/models.py` (`ResearchFile`). Ids are kebab-case and permanent. Before creating an entity, check `matches` and reuse the existing id; ingest rejects a new entity whose name or alias matches an existing one.

- `trends`: id, name, summary, aliases, `search_terms` (English queries a user would type), regions, platforms, origin.
- `formats`: the reusable pattern - what the user inputs, what they get.
- `opportunities`: what we could ship; `product_type` video / image / audio / effect / multi / other.
- `links`: trend -uses-> format, format -enables-> opportunity, trend -drives-> opportunity, trend -searched_as-> keyword, opportunity -targets-> keyword, any -competitor|related-> site, trend/format -related|variant_of-> same kind. Many-to-many is normal; never force one-to-one.
- `evidence`: one row per observation, with `channel`, `source`, `url`, `metric`, `value`, `unit`, `region`, `sample_size`, `metric_definition`, `collected_at` (with offset), `confidence`, `tag` (已核实 / 第三方读数 / 估算), optional `api_call_id`, and a `ref` so assessments can cite it. A ref is unique across the whole database, forever: re-ingesting the identical row is a no-op, but a ref that already names different evidence (any day, including today) is rejected. A new observation gets a new ref, e.g. `tt-aibabydance-posts-20261114`. Evidence is append-only; without a ref, changing any field stores a new row instead of replacing the old one. Qualitative evidence leaves `value` empty and explains in `note`. Keep metric names stable across days for the same series (`posts_24h`, `views_top10_remix`, `cc_index`, `search_volume`, ...): backtests follow them.
- `gaps`: everything you tried and could not get, with why. Missing is not zero; never interpolate.
- `social_coverage` (required): one entry per source: TikTok, CapCut, Instagram, X, YouTube, Creative Center, Watchlist. Give `status` (covered / partial / failed / not_attempted), `window` (approximate time window searched; required unless failed or not attempted), `signals` (found / none; `unknown` only for a source not fully covered) and `note` (what you did; for anything not covered, the reason: login wall, rate limit, out of time). Anything not covered becomes a gap automatically. The daily report shows this table and a one-line summary, so be honest: a source you didn't open is `not_attempted`, not `covered`.
- `notes`: run-level remarks (method changes, what you would do with more time). Persisted and shown in the report.

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

`run` writes `reports/daily/DAY.md` and the in-depth reports, then publishes them to Lark. Reply in chat with: the key opportunities (four attributes + one line each), new early signals, decision changes, the backtest line, gaps, credits spent today, local report paths and the Lark URLs (copy them from `status DAY`; report any document that is not `synced`, with its error). If nothing changed, say so in one line.

## Human feedback

People change decisions, priorities, lifecycle, links or research direction by dropping a JSON file into `<data>/feedback/` (schema `FeedbackFile`):

```json
{"feedback": [{"entity": "opportunity:baby-dance-template", "field": "priority", "value": "P1",
  "reason": "team capacity", "author": "name", "at": "2026-11-14T09:00:00+08:00"}]}
```

`field` is decision / priority / lifecycle / link_add / link_remove (`value` = `relation->kind:id`) / direction (free text guiding your next research). Links in feedback go through the same check as `research.json` links: allowed relation, correct direction, and both ends must exist. Each item is applied once. The agent's original assessment is never changed; the effective state shows both. The draft shows them under `facts.human_feedback`; act on research directions in your next sweep.

## Lark

Only finished reports go to Lark: one document per daily report, one document per key opportunity (overwritten with its latest in-depth report). Never upload the database, raw API data, batches, social data or intermediate files. Settings `[lark]`: `daily_parent` (Wiki node token, required), `opportunity_parent`, `identity`. Destinations must be Wiki nodes, because only those can be checked for edit permission without writing. Publishing uses `lark-cli docs +create/+update` with the user's login. A publish failure fails the run; the next run (after the gate) retries only the unpublished documents and never creates a duplicate, because document ids live in `lark_docs`.

## Recovery

Rerun `run` with the same DAY. The preflight gate runs first every time. Finished sync units are skipped and failed ones retried. Ingest is idempotent, and unchanged reports are neither rewritten nor republished. Use `status DAY` to see where it stopped.
- Reports are reproducible: a report for day D only uses what was ingested into the database by the end of D (rules in `docs/research-method.md`, "Time"). Rebuilding an old day never pulls in later data, and an early `collected_at` or feedback `at` does not put anything into an older report.
- Research and assessments can only be written for today. Rerunning an old day with identical files is a no-op; a changed file for a past day is refused ("Backdated or future research is not accepted"). Put late findings in today's research.json, with their true `collected_at`. Feedback can be added on any day and counts from when it was ingested.
- Exit 4: NOT READY. Follow Daily procedure step 0 (report everything, wait, recheck, continue).
- Exit 3: another run is in progress. Wait for it; never delete `run.lock`. A leftover file from a crashed run doesn't block anything, because the OS releases the lock when the process dies.
- Rejected input file: fix that file. Never edit the database to get past a check.
- `schema version N; this code needs M`: the database was made by an incompatible version. There are no migrations. Ask the user before moving `radar.db` aside; a fresh store is then created on the next run.
- Config error: it names the file and key. Fix `settings.toml`; the message never contains values.

## Changing code

`uv run pytest` must pass. Keep judgments out of `src/`: no trend names, dates or verdicts. The Ge Fei catalog is read live from `/api/v1/tools` and `/api/openapi.json`; never hand-maintain an endpoint list. A new normalized Ge Fei table belongs in `src/radar/gefei/normalize.py` with its DDL in `src/radar/db.py`.
