#!/usr/bin/env python3
"""Full Keyword Planner research. Never print secrets."""
from __future__ import annotations

import csv
import json
import os
import re
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import paths as P  # noqa: E402

OUT = P.google_ads_output_dir()
ENV_PATH = P.google_ads_env_file()
TOKEN_PATH = OUT / ".access_token"
LOG_PATH = OUT / "run.log"
RAW_DIR = OUT / "raw"


def _ensure_out() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

CUSTOMER_ID = "7611906858"
BASE = f"https://googleads.googleapis.com/v26/customers/{CUSTOMER_ID}"
LANG = "languageConstants/1000"
NETWORK = "GOOGLE_SEARCH"

GEOS = {
    "US": "geoTargetConstants/2840",
    "GB": "geoTargetConstants/2826",
    "AU": "geoTargetConstants/2036",
    "CA": "geoTargetConstants/2124",
    "DE": "geoTargetConstants/2276",
    "JP": "geoTargetConstants/2392",
    "KR": "geoTargetConstants/2410",
    "FR": "geoTargetConstants/2250",
    "NL": "geoTargetConstants/2528",
}

# 6-month window requested
WINDOW_MONTHS = [
    ("APRIL", "2026"),
    ("MAY", "2026"),
    ("JUNE", "2026"),
    ("JULY", "2026"),
    ("AUGUST", "2026"),
    ("SEPTEMBER", "2026"),
]
TREND_START = ("APRIL", "2026")
TREND_END = ("SEPTEMBER", "2026")

SEED_BATCHES = {
    "generic_meme_video": [
        "ai meme video",
        "ai meme video generator",
        "meme video maker",
        "ai meme generator",
        "video meme generator",
    ],
    "template_trend": [
        "ai trend video",
        "trend template",
        "viral video template",
        "ai video template",
        "meme template video",
    ],
    "dance": [
        "ai dance video",
        "ai dance generator",
        "make me dance ai",
    ],
    "faceswap_photo": [
        "face swap meme",
        "ai video face swap",
        "photo to video ai",
        "ai video effects",
    ],
    "brand": [
        "capcut template",
        "capcut ai template",
        "capcut meme template",
        "tiktok ai filter",
        "tiktok trend template",
        "viggle ai",
    ],
    "meme_names": [
        "bicep heart",
        "cat on ultra bee",
        "ba ba ba dance",
        "malfoid",
        "punching cat",
        "black cat clapping",
        "hippo crocodile little cousins",
        "bicep heart meme",
        "bicep heart trend",
        "punching cat meme",
        "punching cat gif",
        "black cat clapping meme",
        "little cousins meme",
        "shoulder carry meme",
        "can i ride meme",
        "flamingo float meme",
        "cat on ultra bee meme",
        "malfoid meme",
    ],
}

# Exact terms always included in historical pull (even if ideas skip them)
ALWAYS_INCLUDE = []
for batch in SEED_BATCHES.values():
    ALWAYS_INCLUDE.extend(batch)
ALWAYS_INCLUDE += [
    "shoulder carry",
    "can i ride",
    "flamingo float",
    "ai remix video",
    "remix video ai",
    "trend remix",
    "face swap video",
    "ai face swap video",
    "photo to meme video",
    "viral meme template",
    "ai gif meme",
    "gif meme ai",
    "make punching cat",
    "punching cat template",
    "bicep heart template",
    "bicep heart dance",
    "viggle dance",
    "capcut ai meme",
    "tiktok meme template",
]
ALWAYS_INCLUDE = list(dict.fromkeys(ALWAYS_INCLUDE))

BRAND_TOKENS = [
    "capcut",
    "cap cut",
    "tiktok",
    "tik tok",
    "viggle",
    "kwai",
    "douyin",
    "instagram",
    "ig reels",
    "youtube",
    "filmora",
    "canva",
    "invideo",
    "runway",
    "pika",
    "kling",
    "luma",
    "sora",
    "higgsfield",
    "lemon8",
    "cap-cut",
    "vn video",
    "inshot",
    "alight motion",
    "premiere",
    "after effects",
    "davinci",
    "meitu",
    "hypic",
    "tempalte",  # typo variants still brand if with capcut etc.
]


def log(msg: str) -> None:
    _ensure_out()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in ENV_PATH.read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_access_token(force: bool = False) -> str:
    if not force and TOKEN_PATH.exists():
        age = time.time() - TOKEN_PATH.stat().st_mtime
        if age < 3000:  # refresh a bit early
            tok = TOKEN_PATH.read_text().strip()
            if tok:
                return tok
    env = load_env()
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": env["GOOGLE_ADS_CLIENT_ID"],
            "client_secret": env["GOOGLE_ADS_CLIENT_SECRET"],
            "refresh_token": env["GOOGLE_ADS_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=60,
    )
    ctype = resp.headers.get("content-type", "")
    if "application/json" not in ctype:
        log(f"TOKEN_ERROR status={resp.status_code} content-type={ctype} body_len={len(resp.text)}")
        raise SystemExit("Token exchange returned non-JSON")
    payload = resp.json()
    if "access_token" not in payload:
        log(f"TOKEN_ERROR keys={list(payload.keys())} error={payload.get('error')}")
        raise SystemExit("Token exchange missing access_token")
    token = payload["access_token"]
    TOKEN_PATH.write_text(token)
    os.chmod(TOKEN_PATH, 0o600)
    log(f"Refreshed access token, expires_in={payload.get('expires_in')}s")
    return token


def ads_post(endpoint: str, body: dict[str, Any], retries: int = 8) -> dict[str, Any]:
    url = f"{BASE}:{endpoint}"
    token = get_access_token()
    last = None
    for attempt in range(1, retries + 1):
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, headers=headers, json=body, timeout=180)
        if resp.status_code == 401 and attempt <= 2:
            log(f"{endpoint} 401, refreshing token")
            token = get_access_token(force=True)
            continue
        if resp.status_code == 200:
            return resp.json()
        snippet = resp.text[:500].replace("\n", " ")
        retryable = resp.status_code in (429, 500, 503) or any(
            s in resp.text for s in ("RESOURCE_EXHAUSTED", "RATE_LIMIT", "UNAVAILABLE", "internal error")
        )
        log(f"{endpoint} status={resp.status_code} attempt={attempt} snippet={snippet}")
        if retryable:
            wait = min(90, 2 ** attempt)
            time.sleep(wait)
            last = resp
            continue
        raise SystemExit(f"{endpoint} failed with {resp.status_code}")
    raise SystemExit(f"{endpoint} failed after retries, last={getattr(last, 'status_code', None)}")


def fetch_ideas(name: str, seeds: list[str], geo_label: str, geo_ids: list[str]) -> list[dict[str, Any]]:
    cache = RAW_DIR / f"ideas_{name}_{geo_label}.json"
    if cache.exists():
        data = json.loads(cache.read_text())
        results = data.get("results") or []
        log(f"CACHE ideas {name}/{geo_label}: {len(results)} results")
        return results

    all_results: list[dict[str, Any]] = []
    page_token = None
    page = 0
    while True:
        page += 1
        body: dict[str, Any] = {
            "language": LANG,
            "geoTargetConstants": geo_ids,
            "keywordPlanNetwork": NETWORK,
            "keywordSeed": {"keywords": seeds},
            "pageSize": "1000",
        }
        if page_token:
            body["pageToken"] = page_token
        data = ads_post("generateKeywordIdeas", body)
        results = data.get("results") or []
        all_results.extend(results)
        log(
            f"ideas {name}/{geo_label} page={page} got={len(results)} total_so_far={len(all_results)} "
            f"totalSize={data.get('totalSize')} next={bool(data.get('nextPageToken'))}"
        )
        page_token = data.get("nextPageToken")
        # Save incrementally
        cache.write_text(json.dumps({"results": all_results, "totalSize": data.get("totalSize")}, ensure_ascii=False))
        if not page_token:
            break
        time.sleep(0.8)
    time.sleep(0.6)
    return all_results


def is_mostly_english(text: str) -> bool:
    # Allow ascii letters, digits, spaces, basic punct. Reject if many CJK/Hangul/Kana.
    non_latin = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", text))
    if non_latin >= 1:
        return False
    letters = re.findall(r"[A-Za-z]", text)
    if not letters:
        return False
    return True


MEME_NAME_PATTERNS = [
    r"\bbicep heart\b",
    r"\bbicep hearts?\b",
    r"\bshoulder carry\b",
    r"\bcan i ride\b",
    r"\bcat on ultra bee\b",
    r"\bultra bee\b",
    r"\bba ba ba dance\b",
    r"\bbabababa\b",
    r"\bflamingo float\b",
    r"\bmalfoid\b",
    r"\bpunching cat\b",
    r"\bpunchingcat\b",
    r"\bblack cat clapping\b",
    r"\bclapping cat\b",
    r"\blittle cousins\b",
    r"\bhippo crocodile\b",
    r"\bhippo and crocodile\b",
]


def is_brand(text: str) -> bool:
    t = text.lower()
    return any(b in t for b in BRAND_TOKENS)


def classify(text: str) -> tuple[bool, str, str]:
    """Return (keep, category, reason). Category is primary; brand terms still get a brand flag later."""
    t = text.lower().strip()
    t_norm = re.sub(r"\s+", " ", t)

    if not is_mostly_english(t_norm):
        return False, "", "not_english"

    # obvious junk
    junk = [
        "pool float",
        "pool flamingo",
        "inflatable",
        "workout",
        "gym ",
        "exercise",
        "dumbbell",
        "physical therapy",
        "how to shoulder carry",
        "fireman carry",
        "lyrics",
        "roblox",
        "fortnite",
        "minecraft",
        "free fire",
        "apk",
        "mod apk",
        "job",
        "salary",
        "near me",
        "stock photo",
        "onlyfans",
        "porn",
        "xxx",
    ]
    # Don't junk if clearly meme/template/ai video
    on_intent_hint = any(
        k in t_norm
        for k in (
            "meme",
            "capcut",
            "tiktok",
            "viggle",
            "face swap",
            "faceswap",
            "ai video",
            "ai dance",
            "template",
            "trend video",
        )
    )
    if not on_intent_hint:
        for j in junk:
            if j in t_norm:
                return False, "", f"junk:{j}"

    for pat in MEME_NAME_PATTERNS:
        if re.search(pat, t_norm):
            # drop obvious non-meme if no meme/gif/trend/template/ai and it's a generic product
            if re.search(r"\b(pool|inflatable|floatie|air mattress|workout|gym)\b", t_norm) and not on_intent_hint:
                return False, "", "meme_name_but_unrelated"
            return True, "specific_meme_name", "meme_name"

    # brand-only generic (just "tiktok" or "capcut download") — keep only if related to templates/ai/meme/trend/filter/dance
    brand = is_brand(t_norm)

    has_video = bool(re.search(r"\b(video|videos|clip|reel|reels|gif|gifs)\b", t_norm))
    has_template = bool(re.search(r"\b(template|templates|trend|trends|viral|remix|remake|recreate)\b", t_norm))
    has_meme = bool(re.search(r"\b(meme|memes)\b", t_norm))
    has_ai = bool(re.search(r"\b(ai|artificial intelligence|chatgpt|gpt)\b", t_norm))
    has_dance = bool(re.search(r"\b(dance|dancing|dances)\b", t_norm))
    has_faceswap = bool(re.search(r"\b(face ?swap|faceswap|face swap)\b", t_norm))
    has_photo2vid = bool(
        re.search(
            r"\b((photo|image|pic|picture) ?to ?video|image to video|photo to video|img to video|pic to video)\b",
            t_norm,
        )
    )
    has_effects = bool(re.search(r"\b(video effects?|ai effects?)\b", t_norm))
    has_maker = bool(re.search(r"\b(generator|maker|creator|editor|generate|make)\b", t_norm))

    # Category assignment (non-brand primary)
    if has_dance and (has_ai or has_template or "make me dance" in t_norm or "make you dance" in t_norm or brand):
        return True, "dance", "dance"
    if has_faceswap and (has_video or has_meme or has_ai or has_template or brand):
        return True, "face_swap_photo_to_video", "faceswap"
    if has_photo2vid and (has_ai or has_meme or brand):
        return True, "face_swap_photo_to_video", "photo_to_video"
    if has_meme and has_video and (has_ai or has_maker or has_template):
        return True, "generic_ai_meme_video", "meme_video"
    if has_meme and has_ai:
        # may be static image — keep in generic but we'll note it
        return True, "generic_ai_meme_video", "ai_meme_maybe_static"
    if has_template and (has_ai or has_meme or "video template" in t_norm or "trend template" in t_norm or brand):
        return True, "template_remix", "template"
    if has_ai and has_video and has_effects:
        return True, "face_swap_photo_to_video", "ai_video_effects"
    if has_ai and has_video and (has_maker or "trend" in t_norm):
        return True, "generic_ai_meme_video", "ai_video_adjacent"
    if brand and (has_template or has_meme or has_ai or has_dance or "filter" in t_norm or "effect" in t_norm):
        return True, "template_remix", "brand_related"

    return False, "", "off_intent"


def micros_to_usd(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return round(int(v) / 1_000_000, 2)
    except (TypeError, ValueError):
        return None


def month_vol(volumes: list[dict[str, Any]], month: str, year: str) -> int | None:
    for v in volumes:
        if str(v.get("month")) == month and str(v.get("year")) == year:
            try:
                return int(v.get("monthlySearches") or 0)
            except (TypeError, ValueError):
                return None
    return None


def window_stats(volumes: list[dict[str, Any]]) -> dict[str, Any]:
    vals = []
    monthly = {}
    for m, y in WINDOW_MONTHS:
        val = month_vol(volumes, m, y)
        key = f"{y}-{m[:3].title()}"
        # Use calendar month number in key
        monthly[f"{y}-{_month_num(m):02d}"] = val
        if val is not None:
            vals.append(val)
    avg6 = round(sum(vals) / len(vals), 1) if vals else None
    apr = month_vol(volumes, *TREND_START)
    sep = month_vol(volumes, *TREND_END)
    if apr is None or sep is None:
        pct = None
        trend = None
    elif apr == 0 and sep == 0:
        pct = 0.0
        trend = "flat"
    elif apr == 0 and sep > 0:
        pct = None  # cannot compute % from 0; flag as new/rising from zero
        trend = "from_zero"
    else:
        pct = round((sep - apr) / apr * 100, 1)
        if pct >= 20:
            trend = "up"
        elif pct <= -20:
            trend = "down"
        else:
            trend = "flat"
    return {
        "avg6": avg6,
        "apr": apr,
        "sep": sep,
        "pct": pct,
        "trend": trend,
        "monthly": monthly,
        "n_months": len(vals),
    }


def _month_num(name: str) -> int:
    names = {
        "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
        "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
    }
    return names[name]


def fetch_historical(keywords: list[str], geo_label: str, geo_ids: list[str]) -> list[dict[str, Any]]:
    # Cache by hash of keyword set + geo
    safe_name = f"hist_{geo_label}_{len(keywords)}.json"
    # Better: split into chunks of 800 and cache each chunk
    chunk_size = 800
    all_results: list[dict[str, Any]] = []
    for i in range(0, len(keywords), chunk_size):
        chunk = keywords[i : i + chunk_size]
        cache = RAW_DIR / f"hist_{geo_label}_chunk{i//chunk_size}_{len(chunk)}.json"
        if cache.exists():
            data = json.loads(cache.read_text())
            results = data.get("results") or []
            log(f"CACHE hist {geo_label} chunk={i//chunk_size} n={len(results)}")
            all_results.extend(results)
            continue
        body = {
            "keywords": chunk,
            "language": LANG,
            "geoTargetConstants": geo_ids,
            "keywordPlanNetwork": NETWORK,
        }
        data = ads_post("generateKeywordHistoricalMetrics", body)
        results = data.get("results") or []
        cache.write_text(json.dumps(data, ensure_ascii=False))
        log(f"hist {geo_label} chunk={i//chunk_size} requested={len(chunk)} results={len(results)}")
        all_results.extend(results)
        time.sleep(0.7)
    return all_results


def main() -> None:
    log("=== START research ===")
    get_access_token()

    # 1) Ideas: combined 9 geos, and US
    all_idea_rows = []
    for batch_name, seeds in SEED_BATCHES.items():
        for geo_label, geo_ids in (
            ("COMBINED9", list(GEOS.values())),
            ("US", [GEOS["US"]]),
        ):
            # Skip US ideas for meme_names to reduce noise; combined is enough
            if batch_name == "meme_names" and geo_label == "US":
                continue
            results = fetch_ideas(batch_name, seeds, geo_label, geo_ids)
            for r in results:
                km = r.get("keywordIdeaMetrics") or {}
                all_idea_rows.append(
                    {
                        "source_batch": batch_name,
                        "source_geo": geo_label,
                        "text": (r.get("text") or "").strip(),
                        "avg_monthly_searches_12m": _to_int(km.get("avgMonthlySearches")),
                        "competition": km.get("competition"),
                        "competition_index": _to_int(km.get("competitionIndex")),
                        "low_cpc_usd": micros_to_usd(km.get("lowTopOfPageBidMicros")),
                        "high_cpc_usd": micros_to_usd(km.get("highTopOfPageBidMicros")),
                        "close_variants": r.get("closeVariants") or [],
                        "monthly_volumes": km.get("monthlySearchVolumes") or [],
                    }
                )

    # Unique keyword texts from ideas + always include
    texts = []
    seen = set()
    for row in all_idea_rows:
        t = row["text"].strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            texts.append(t)
        for cv in row.get("close_variants") or []:
            cv = (cv or "").strip()
            if cv and cv.lower() not in seen:
                seen.add(cv.lower())
                texts.append(cv)
    for t in ALWAYS_INCLUDE:
        if t.lower() not in seen:
            seen.add(t.lower())
            texts.append(t)

    log(f"Unique idea+seed terms: {len(texts)}")

    # Filter
    kept, dropped = [], []
    for t in texts:
        keep, cat, reason = classify(t)
        rec = {"keyword": t, "category": cat, "reason": reason, "is_brand": is_brand(t)}
        if keep:
            kept.append(rec)
        else:
            dropped.append(rec)
    log(f"Kept {len(kept)} / dropped {len(dropped)}")

    # Write filter lists
    with (OUT / "keywords_kept.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["keyword", "category", "reason", "is_brand"])
        w.writeheader()
        w.writerows(kept)
    with (OUT / "keywords_dropped.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["keyword", "category", "reason", "is_brand"])
        w.writerows(dropped)

    keywords = [r["keyword"] for r in kept]
    # Ensure always-include exact seeds that were dropped for off-intent still get historical if they were seed names
    for t in ALWAYS_INCLUDE:
        if t.lower() not in {k.lower() for k in keywords}:
            # only force-include the original brief seeds and tight variants, not junk expansions
            keep, cat, reason = classify(t)
            # force include brief seeds even if classifier unsure
            keywords.append(t)
            kept.append({"keyword": t, "category": cat or "specific_meme_name", "reason": "force_seed", "is_brand": is_brand(t)})
            log(f"Force-included seed: {t} cat={cat or 'specific_meme_name'} reason={reason}")

    # Dedup keywords preserving order
    uniq, seenk = [], set()
    for k in keywords:
        if k.lower() not in seenk:
            seenk.add(k.lower())
            uniq.append(k)
    keywords = uniq
    log(f"Historical keyword count: {len(keywords)}")
    (RAW_DIR / "historical_keyword_list.json").write_text(json.dumps(keywords, ensure_ascii=False, indent=2))

    # 2) Historical per country + combined
    geo_scopes = [("COMBINED9", list(GEOS.values()))] + [(code, [gid]) for code, gid in GEOS.items()]
    hist_by_geo: dict[str, list[dict[str, Any]]] = {}
    for label, ids in geo_scopes:
        hist_by_geo[label] = fetch_historical(keywords, label, ids)

    # Parse into raw monthly rows and summary
    cat_map = {r["keyword"].lower(): r for r in kept}

    raw_fields = [
        "keyword",
        "category",
        "is_brand",
        "country",
        "year_month",
        "monthly_searches",
        "avg_monthly_searches_12m",
        "competition",
        "competition_index",
        "low_top_of_page_bid_usd",
        "high_top_of_page_bid_usd",
        "close_variants",
        "canonical_text",
    ]
    summary_fields = [
        "keyword",
        "category",
        "is_brand",
        "country",
        "avg_6m_apr_sep_2026",
        "apr_2026",
        "may_2026",
        "jun_2026",
        "jul_2026",
        "aug_2026",
        "sep_2026",
        "trend_apr_to_sep_pct",
        "trend_flag",
        "avg_monthly_searches_12m",
        "competition",
        "competition_index",
        "low_top_of_page_bid_usd",
        "high_top_of_page_bid_usd",
        "close_variants",
        "canonical_text",
    ]

    raw_rows = []
    summary_rows = []

    for country, results in hist_by_geo.items():
        for r in results:
            text = (r.get("text") or "").strip()
            km = r.get("keywordMetrics") or {}
            volumes = km.get("monthlySearchVolumes") or []
            meta = cat_map.get(text.lower(), {})
            # If API folded a keyword into a close variant canonical text, try original later
            close = r.get("closeVariants") or []
            rec_base = {
                "keyword": text,
                "category": meta.get("category") or classify(text)[1] or "",
                "is_brand": meta.get("is_brand") if "is_brand" in meta else is_brand(text),
                "country": country,
                "avg_monthly_searches_12m": _to_int(km.get("avgMonthlySearches")),
                "competition": km.get("competition") or "",
                "competition_index": _to_int(km.get("competitionIndex")),
                "low_top_of_page_bid_usd": micros_to_usd(km.get("lowTopOfPageBidMicros")),
                "high_top_of_page_bid_usd": micros_to_usd(km.get("highTopOfPageBidMicros")),
                "close_variants": "|".join(close) if close else "",
                "canonical_text": text,
            }
            # monthly raw
            for v in volumes:
                ym = f"{v.get('year')}-{_month_num(str(v.get('month'))):02d}"
                raw_rows.append(
                    {
                        **rec_base,
                        "year_month": ym,
                        "monthly_searches": _to_int(v.get("monthlySearches")),
                    }
                )
            st = window_stats(volumes)
            monthly = st["monthly"]
            summary_rows.append(
                {
                    **rec_base,
                    "avg_6m_apr_sep_2026": st["avg6"],
                    "apr_2026": monthly.get("2026-04"),
                    "may_2026": monthly.get("2026-05"),
                    "jun_2026": monthly.get("2026-06"),
                    "jul_2026": monthly.get("2026-07"),
                    "aug_2026": monthly.get("2026-08"),
                    "sep_2026": monthly.get("2026-09"),
                    "trend_apr_to_sep_pct": st["pct"],
                    "trend_flag": st["trend"],
                }
            )

    # Also record requested keywords that didn't come back (zero / not found)
    returned_by_geo = {g: { (r.get("text") or "").lower() for r in results } for g, results in hist_by_geo.items()}
    # close variant mapping
    variant_to_canonical = defaultdict(dict)
    for country, results in hist_by_geo.items():
        for r in results:
            canon = (r.get("text") or "").lower()
            for cv in r.get("closeVariants") or []:
                variant_to_canonical[country][cv.lower()] = canon
            variant_to_canonical[country][canon] = canon

    missing_log = []
    for country, results in hist_by_geo.items():
        returned = returned_by_geo[country]
        aliases = variant_to_canonical[country]
        for kw in keywords:
            if kw.lower() not in aliases and kw.lower() not in returned:
                missing_log.append({"country": country, "keyword": kw})

    log(f"Raw monthly rows={len(raw_rows)} summary rows={len(summary_rows)} missing={len(missing_log)}")

    with (OUT / "keyword_monthly_raw.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=raw_fields)
        w.writeheader()
        w.writerows(raw_rows)
    with (OUT / "keyword_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=summary_fields)
        w.writeheader()
        w.writerows(summary_rows)
    with (OUT / "keywords_missing_in_api.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["country", "keyword"])
        w.writeheader()
        w.writerows(missing_log)

    # Quick combined9 top preview
    comb = [s for s in summary_rows if s["country"] == "COMBINED9"]
    comb_sorted = sorted(comb, key=lambda x: (x["avg_6m_apr_sep_2026"] is None, -(x["avg_6m_apr_sep_2026"] or 0)))
    log("TOP 20 COMBINED9 by 6m avg:")
    for i, s in enumerate(comb_sorted[:20], 1):
        log(
            f"  {i:2d}. {s['keyword']!r} brand={s['is_brand']} cat={s['category']} "
            f"avg6={s['avg_6m_apr_sep_2026']} apr={s['apr_2026']} sep={s['sep_2026']} "
            f"pct={s['trend_apr_to_sep_pct']} comp={s['competition']} "
            f"cpc={s['low_top_of_page_bid_usd']}-{s['high_top_of_page_bid_usd']}"
        )
    log("=== DONE fetch/parse ===")


def _to_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log("UNCAUGHT:\n" + traceback.format_exc())
        raise
