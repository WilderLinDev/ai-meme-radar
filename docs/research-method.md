# Research method

How AI Meme Radar decides. Terms are defined in `GLOSSARY.md`; the daily procedure is in `.agents/skills/ai-meme-radar/SKILL.md`.

## Research model

```
Trend ──uses──▶ Format ──enables──▶ Template opportunity
  │                                     ▲
  └────────────────drives───────────────┘
Trend ──searched_as──▶ keyword      Opportunity ──targets──▶ keyword
any ──competitor / related──▶ site
```

All relations are many-to-many. A trend without a known format is fine (early signal); a format may serve several trends; an opportunity may combine formats.

## Four channels, two-way discovery

| Channel | Who collects | Typical sources |
| --- | --- | --- |
| social | agent, browser | TikTok, CapCut templates, Instagram Reels, X, YouTube Shorts, Reddit, Creative Center, watchlist |
| search | Python (sync) + agent (queries) | Ge Fei emerging keywords, keyword_volume, google_trends, trends_rising, keyword_ideas, search_intent, serp, keyword_difficulty |
| product | Python (sync) + agent | Ge Fei launches and website discovery, search_known_sites, domain_overview, site_keywords |
| market | Python (sync) + agent | Ge Fei revenue data, stripe_checkout_referrals, domain_traffic, site_history, website_worth, domain_dr, backlink_value |

Directions that must all be tried: social trend → keywords → search demand; emerging keyword → the social trend behind it; new site → its trend and keywords; trend → existing competing products. Early signals may lack search data; that is recorded, not penalised into a score.

Estimated traffic is not revenue. Ge Fei's own verdicts and briefs are inputs, never our conclusion.

## Four independent attributes

| Attribute | Values | Question it answers |
| --- | --- | --- |
| lifecycle | early_signal, emerging, proven, fading | Where is the trend in its life? |
| decision | build, validate, monitor, skip | What do we do about it now? |
| priority | P0–P3 | How soon, relative to everything else? |
| confidence | high, medium, low | How strong is the evidence behind this judgment? |

They do not constrain each other. `emerging + validate + P0 + medium` means: growing, worth testing right away, evidence not yet sufficient.

Guidance, not rules:
- **build**: demand is visible in at least two channels, the format is reproducible with current AI tools, and the window is open. Needs next steps a team can start today.
- **validate**: promising but one key question is open (search demand, feasibility, competition). Name the cheapest test that answers it.
- **monitor**: real but not actionable yet, or crowded; say what would change the call.
- **skip**: not a template opportunity (no reusable format, unlicensable IP or likeness, brand-unsafe, politics, adult) or the window has closed. Say which.

## Seven dimensions

Each gets a level (high / medium / low / unknown), a note saying what it rests on, and evidence refs. `unknown` is honest; a guess dressed as `medium` is not.

| Dimension | High means |
| --- | --- |
| social_momentum | volume and growth of posts / remixes are high and rising |
| search_demand | people search for it (volume, rising trends, intent to make or download) |
| audience_participation | people imitate it: templates used, remixes, duets, "how do I make this" |
| template_potential | one input → one satisfying output, repeatable without skill |
| ai_feasibility | today's models produce it reliably, fast and cheaply enough |
| competition | the space is crowded (many tools / templates already rank or sell) |
| timing | the window is open now and will stay open long enough to ship |

There is no overall score and no weighting. The decision explains how the dimensions were traded off.

## Evidence standards

Every conclusion keeps its source, collection time, region, sample size, metric definition and confidence. Inferences and unvalidated assumptions go in `assumptions`, not in the rationale as facts. Numbers cited from Ge Fei carry the `api_call_id`; ingest checks that the value appears in the stored response unless it is tagged 估算.

## Time: research day, observed at, ingested at

Every record keeps up to three times, and they are never mixed:

| Time | Meaning | Fields |
| --- | --- | --- |
| research day | the day the record belongs to | `day` on evidence, assessments, link events, gaps, research_days |
| observed at | when the original observation happened | evidence `collected_at`, backtest `outcome_at`, feedback `at` (user-supplied) |
| ingested at | when it actually entered `radar.db` (wall clock, Asia/Shanghai) | evidence / feedback / gaps `ingested_at`, assessments `created_at`, link events `at`, research_days `updated_at`, backtest `outcome_ingested_at`, keyword snapshots `captured_at` |

Only ingested-at proves the store knew something. A report for day D uses only records ingested by the end of D:
- the latest assessment revision among those created by then (the cutoff is applied before picking the revision);
- feedback ingested by then, applied over the assessment it was ingested after;
- links replayed in insertion order from events recorded by then;
- evidence, gaps and research metadata ingested by then;
- backtests recomputed from the observations ingested by then. An outcome observed on the 20th and ingested on the 22nd settles on the 22nd, and keeps the 20th as its observation date.

Deep reports show evidence and links as ingested when their assessment revision was created, and feedback and backtests as of the report day.

Research for a day can only be written on that day: re-ingesting identical research or assessments for another day is a no-op, but anything new for a past or future research day is refused. This keeps "research day D" and "known on D" the same thing without bitemporal bookkeeping. Feedback has no research day and can be added any time; it counts from when it was ingested.

Known limit: entity names and descriptions are not versioned, so an old report rebuilt later shows the current name.

## Lifecycle-specific depth

| Lifecycle | In-depth report focuses on |
| --- | --- |
| early_signal | what was discovered, first evidence, potential |
| emerging | growth speed, spread across platforms and regions, how to validate |
| proven | market demand, competition, productization |
| fading | why it declines, remaining window, reusable value |

## Backtests

Both use the tracked series and the baseline frozen at assessment time. A value observed later, even one back-dated, never replaces the baseline. Only the final revision of each entity on each assessment day counts in official results. Results of superseded revisions stay stored for audit but never enter hit rates. Historical views follow the time rules above.

Observations are compared only when they measure the same thing: the same source, metric, unit, metric definition and region (for keyword heat, the same keyword). The baseline freezes this identity, and an outcome must match it. The daily report likewise compares a tracked value with the previous report only when the identity is unchanged; otherwise it says the definition changed and computes no growth.

**Lifecycle (7 days)**: compare the first observation at or after day + 7 (within 7 more days) with the baseline. Expected direction: early_signal / emerging → rising (≥ +15%), proven → holding (> −15%), fading → falling (≤ −15%), unless the assessment set `expected_direction`.

**Decision (14 days, opportunities)**: build / validate are *supported* if the series held (≥ −10%); monitor is *missed upside* and skip is *missed* if it rose ≥ +30%.

No observation in the window → `pending`, then `no_data`. No tracked series → `unscorable`. When a backtest misses, write how you adjust in the next assessment's notes. Human overrides are reported beside the agent's record and do not rewrite it.
