#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preflight for a daily digest. Do not ask about scope.

Prints which settings and secrets are present or missing, and which
pipeline steps will run or be skipped. Ask only for lines under Ask.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths as P  # noqa: E402

REGIONS = ("US", "GB", "AU", "CA", "DE", "JP", "KR", "FR")
LARK_TABLES_FOR_SYNC = (
    "cc_rank_snapshot",
    "cc_hashtag_curve",
    "cc_hashtag_audience",
    "meme_daily_tracker",
    "remix_videos",
    "backtest",
    "watchlist",
    "digest_index",
)
ADS_SECRETS = (
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
)


def _watchlist_count() -> int:
    if not P.WATCHLIST.exists():
        return 0
    lines = P.WATCHLIST.read_text(encoding="utf-8").splitlines()
    return max(0, len(lines) - 1)


def _section(title: str, rows: list[str]) -> None:
    print(title)
    if not rows:
        print("  (none)")
        return
    for row in rows:
        print(f"  - {row}")


def main() -> int:
    print("Do not ask about scope. Regions, platforms, watchlist accounts, and language are already set. Use them as-is.")
    print()
    print("Minimum path")
    print("  Lark and Google Ads are optional. With both unset, still write")
    print(f"  {P.REPORTS_DIR}/YYYY-MM/YYYY-MM-DD-daily-report.md and .docx.")
    print("  Ask only for a missing login or setting that blocks one step. Say what it unlocks and what you will skip.")
    print("  Optional gaps are skipped. Do not ask about them.")
    print()
    print("Fixed scope")
    print("  - Platforms: TikTok, then CapCut, then Instagram Reels. Never Douyin.")
    print("  - Creative Center regions: " + ", ".join(REGIONS) + ". NL is not offered; skip it.")
    print("  - Periods: 7 and 30 days. Industry: News & Entertainment.")
    print(f"  - Watchlist: {P.WATCHLIST.relative_to(P.REPO_ROOT)} ({_watchlist_count()} public accounts).")
    print("  - Report language: Chinese. Scoring: docs/scoring.md.")
    print(f"  - Local config directory: {P.config_dir()}")
    print()

    present: list[str] = []
    ask: list[str] = []
    skipped: list[str] = []
    try_first: list[str] = []

    if P.WATCHLIST.exists():
        present.append(f"config/watchlist.csv ({_watchlist_count()} accounts)")
    else:
        ask.append(
            "Coverage needs config/watchlist.csv. Without it, skip the watchlist pull. "
            "The rest of the report still runs."
        )

    reportlib = P.reportlib_dir() / "reportlib" / "docx_report.py"
    if reportlib.exists():
        present.append(f"reportlib at {reportlib.parent}")
    else:
        ask.append(
            f"Word report needs the reportlib package ({reportlib}). "
            "Set paths.reportlib. Without it, skip the .docx. Markdown can still be written by hand."
        )

    if P.FONT.is_file():
        present.append(f"CJK font {P.FONT}")
    else:
        skipped.append(
            f"CJK font is missing ({P.FONT}). Charts fall back to DejaVu Sans and Chinese glyphs in charts may be blank. "
            "The markdown and docx are still written. Set paths.font to improve charts. Do not ask."
        )

    lark = P.lark_config()
    if not P.lark_enabled():
        present.append("lark.enabled = false")
        skipped.append(
            "Lark Wiki import and Base append are skipped. "
            "They unlock a Wiki doc and rows in the Base. Leave them off unless this run should sync. Do not ask."
        )
    else:
        present.append("lark.enabled = true")
        missing = []
        if not str(lark.get("base_app_token") or "").strip():
            missing.append("lark.base_app_token")
        if not str(lark.get("wiki_parent_url") or "").strip():
            missing.append("lark.wiki_parent_url")
        tables = lark.get("tables") or {}
        if not isinstance(tables, dict):
            tables = {}
        for key in LARK_TABLES_FOR_SYNC:
            if not str(tables.get(key) or "").strip():
                missing.append(f"lark.tables.{key}")
        if missing:
            ask.append(
                "Lark sync is on and unlocks Wiki import plus Base append. It needs "
                + ", ".join(missing)
                + f" in {P.config_dir() / 'settings.yaml'}. "
                "Without them, skip Lark only. The report files are still written."
            )
        else:
            present.append("Lark base token, wiki parent, and table ids")
        if not str(lark.get("base_url") or "").strip():
            skipped.append("lark.base_url is empty. Sync can still run. Do not ask.")
        if not str(lark.get("authorized_by") or "").strip():
            skipped.append("lark.authorized_by is empty. Omit it unless a write is rejected. Do not ask.")
        if not any(P.lark_digest_docs().values()):
            skipped.append("lark.digest_docs is empty. Digest-index doc links are skipped. Do not ask.")
        if not str((tables or {}).get("default_table") or "").strip():
            skipped.append("lark.tables.default_table is empty. The empty default table is left as-is. Do not ask.")

    secrets = P.merged_secrets()
    ads_id = P.google_ads_customer_id()
    ads_missing = [key for key in ADS_SECRETS if not secrets.get(key)]
    if ads_id and not ads_missing:
        present.append("Google Ads customer id and OAuth secrets")
    else:
        parts = []
        if not ads_id:
            parts.append("google_ads.customer_id")
        parts.extend(ads_missing)
        skipped.append(
            "Google Ads Keyword Planner is skipped. It unlocks search-volume research in research/ads_keyword_*.py and needs "
            + ", ".join(parts)
            + ". The daily meme report does not use this. Do not ask."
        )
    if not secrets.get("GITHUB_TOKEN"):
        skipped.append(
            "GITHUB_TOKEN is unset. It only unlocks git push when the machine has no git credentials. "
            "Try the normal push first. Ask only if that push fails for lack of auth."
        )
    else:
        present.append("GITHUB_TOKEN")

    try_first.append(
        "X API is not stored in this repo. It unlocks 7-day post counts. "
        "Try it. If unauthorized, ask once, then skip X heat points and record the gap. Do not invent counts."
    )
    try_first.append(
        "TikTok Creative Center browser login is not stored here. It unlocks the 8-region Top 100 and detail pages. "
        "Try it. If logged out, ask once, then skip that bulk pull and say so."
    )
    skipped.append(
        "Instagram login is optional. It unlocks watchlist profile grids. "
        "If login is missing, skip Instagram rows and say so. Do not ask which accounts to drop."
    )

    _section("Present", present)
    print()
    _section("Ask — missing, and this step is skipped without it", ask)
    print()
    _section("Try first — ask only if that pull rejects auth", try_first)
    print()
    _section("Skipped — optional; do not ask", skipped)
    print()
    if ask:
        print("Result: ask only for the Ask lines. The markdown/docx report is still the default output.")
        return 1
    print("Result: minimum path is ready. Do not ask the user. Write the report, and skip the optional steps above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
