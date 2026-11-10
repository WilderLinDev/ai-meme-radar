#!/usr/bin/env python3
"""Google Ads Keyword Planner research. Never print secrets."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import paths as P  # noqa: E402

ENV_PATH = P.google_ads_env_file()
OUT_DIR = P.google_ads_output_dir()
TOKEN_PATH = OUT_DIR / ".access_token"
LOG_PATH = OUT_DIR / "run.log"

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

SEED_KEYWORDS = [
    "ai meme video",
    "ai meme video generator",
    "meme video maker",
    "ai meme generator",
    "video meme generator",
    "ai trend video",
    "trend template",
    "viral video template",
    "ai video template",
    "meme template video",
    "ai dance video",
    "ai dance generator",
    "make me dance ai",
    "face swap meme",
    "ai video face swap",
    "photo to video ai",
    "ai video effects",
    "capcut template",
    "capcut ai template",
    "capcut meme template",
    "tiktok ai filter",
    "tiktok trend template",
    "viggle ai",
    "bicep heart",
    "shoulder carry",
    "can i ride",
    "cat on ultra bee",
    "ba ba ba dance",
    "flamingo float",
    "malfoid",
    "punching cat",
    "black cat clapping",
    "hippo crocodile little cousins",
]


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_access_token(env: dict[str, str]) -> str:
    # Do not log values. Use form-urlencoded so slashes in refresh_token are encoded.
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
        # Do not dump body if it might contain secrets; log status + snippet type only
        log(f"TOKEN_ERROR status={resp.status_code} content-type={ctype} body_len={len(resp.text)}")
        raise SystemExit(f"Token exchange returned non-JSON (status {resp.status_code})")
    payload = resp.json()
    if "access_token" not in payload:
        # Safe keys only
        log(f"TOKEN_ERROR keys={list(payload.keys())} error={payload.get('error')} desc={payload.get('error_description')}")
        raise SystemExit("Token exchange missing access_token")
    token = payload["access_token"]
    expires = payload.get("expires_in")
    TOKEN_PATH.write_text(token)
    os.chmod(TOKEN_PATH, 0o600)
    log(f"Got access token, expires_in={expires}s, token_len={len(token)}")
    return token


def ads_post(token: str, endpoint: str, body: dict[str, Any], retries: int = 6) -> dict[str, Any]:
    url = f"{BASE}:{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        # Intentionally omit developer-token per Rory's instruction.
    }
    last_err = None
    for attempt in range(1, retries + 1):
        resp = requests.post(url, headers=headers, json=body, timeout=180)
        if resp.status_code == 200:
            return resp.json()
        # Retry on rate limits / transient errors
        if resp.status_code in (429, 500, 503) or "RESOURCE_EXHAUSTED" in resp.text or "RATE_LIMIT" in resp.text:
            wait = min(60, 2 ** attempt)
            log(f"{endpoint} status={resp.status_code} attempt={attempt} wait={wait}s body_len={len(resp.text)}")
            # Log a short safe snippet
            snippet = resp.text[:400].replace("\n", " ")
            # Redact any bearer-looking strings just in case
            log(f"  snippet={snippet}")
            time.sleep(wait)
            last_err = resp
            continue
        snippet = resp.text[:800].replace("\n", " ")
        log(f"{endpoint} FATAL status={resp.status_code} snippet={snippet}")
        raise SystemExit(f"{endpoint} failed with {resp.status_code}")
    raise SystemExit(f"{endpoint} failed after retries, last={last_err.status_code if last_err else 'n/a'}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    env = load_env(ENV_PATH)
    needed = [
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
    ]
    missing = [k for k in needed if k not in env]
    if missing:
        raise SystemExit(f"Missing env keys: {missing}")
    if env.get("GOOGLE_ADS_CUSTOMER_ID") and env["GOOGLE_ADS_CUSTOMER_ID"] != CUSTOMER_ID:
        log(f"Note: env customer id differs, using {CUSTOMER_ID} as instructed")
    token = get_access_token(env)

    # Small smoke test
    test_body = {
        "keywords": ["ai meme video", "capcut template"],
        "language": LANG,
        "geoTargetConstants": [GEOS["US"]],
        "keywordPlanNetwork": NETWORK,
    }
    data = ads_post(token, "generateKeywordHistoricalMetrics", test_body)
    results = data.get("results") or []
    log(f"SMOKE historical US results={len(results)} keys={list(data.keys())}")
    if results:
        r0 = results[0]
        log(f"SMOKE first text={r0.get('text')} metric_keys={list((r0.get('keywordMetrics') or r0).keys())}")
        # dump structure (no secrets) for inspection
        (OUT_DIR / "smoke_sample.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
        log("Wrote smoke_sample.json")
    else:
        (OUT_DIR / "smoke_sample.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
        log("SMOKE returned no results; wrote raw payload")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log("UNCAUGHT:\n" + traceback.format_exc())
        raise
