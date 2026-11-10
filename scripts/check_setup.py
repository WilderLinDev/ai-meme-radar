#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Print what a daily run still needs. Do not ask about scope.

Scope (regions, platforms, watchlist, language) is fixed in the repo.
This script only reports missing logins, secrets, and settings.
A blocked step is something the run cannot do until that item is set.
A skipped item is optional: note it and continue. Do not ask about it.
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
    print("Fixed scope")
    print("  - Platforms: TikTok, then CapCut, then Instagram Reels. Never Douyin.")
    print("  - Creative Center regions: " + ", ".join(REGIONS) + ". Skip NL.")
    print("  - Periods: 7 and 30 days. Industry: News & Entertainment.")
    print(f"  - Watchlist file: {P.WATCHLIST.relative_to(P.REPO_ROOT)} ({_watchlist_count()} accounts).")
    print("  - Report language: Chinese. Scoring: docs/scoring.md.")
    print(f"  - Reports directory: {P.REPORTS_DIR}")
    print(f"  - Data directory: {P.DATA_DIR}")
    print()
    print("Ask only when a line below is under Blocked. Say which step needs it and what is skipped without it.")
    print("Lines under Skipped are optional. Note them and continue. Do not ask.")
    print()

    blocked: list[str] = []
    skipped: list[str] = []

    if not P.WATCHLIST.exists():
        blocked.append(
            "Coverage step needs config/watchlist.csv. Without that file, the watchlist pull is skipped."
        )

    font = P.FONT
    if not font.exists():
        blocked.append(
            "scripts/build_report.py needs a CJK font at "
            f"{font}. Set paths.font or put the file there. "
            "Without it, chart generation and the Word report are skipped. "
            "Tracker update and backtest still run."
        )

    reportlib = P.reportlib_dir() / "reportlib"
    if not (reportlib / "docx_report.py").exists():
        blocked.append(
            "scripts/build_report.py needs the reportlib package at "
            f"{reportlib}. Set paths.reportlib if it lives elsewhere. "
            "Without it, the Word report is skipped."
        )

    lark = P.lark_config()
    if not P.lark_enabled():
        skipped.append(
            "Lark Wiki import and Base append are skipped because lark.enabled is false. "
            "Turn it on in local settings only if this run should sync."
        )
    else:
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
            blocked.append(
                "Lark sync is on and needs "
                + ", ".join(missing)
                + f" in {P.config_dir() / 'settings.yaml'} "
                "(or LARK_BASE_APP_TOKEN, LARK_WIKI_PARENT_URL, LARK_TABLE_*). "
                "Without them, Wiki import and Base append are skipped. "
                "The report files are still written and pushed."
            )
        if not str(lark.get("base_url") or "").strip():
            skipped.append("lark.base_url is empty. Sync can still run; the stored Base link is omitted.")
        if not str(lark.get("authorized_by") or "").strip():
            skipped.append("lark.authorized_by is empty. Omit authorizedBy unless a write is rejected for that.")
        docs = P.lark_digest_docs()
        if not any(docs.values()):
            skipped.append("lark.digest_docs is empty. Digest-index doc links are skipped.")
        if not str(tables.get("default_table") or "").strip():
            skipped.append("lark.tables.default_table is empty. The empty default table is left as-is.")

    secrets = P.merged_secrets()
    ads_id = P.google_ads_customer_id()
    ads_missing = [key for key in ADS_SECRETS if not secrets.get(key)]
    if not ads_id or ads_missing:
        parts = []
        if not ads_id:
            parts.append("google_ads.customer_id")
        parts.extend(ads_missing)
        skipped.append(
            "Google Ads Keyword Planner is skipped. It needs "
            + ", ".join(parts)
            + f" ({P.config_dir() / 'settings.yaml'} and {P.config_dir() / '.env'}). "
            "The daily meme report does not need this step."
        )
    if not secrets.get("GOOGLE_ADS_DEVELOPER_TOKEN"):
        skipped.append(
            "GOOGLE_ADS_DEVELOPER_TOKEN is unset. Keyword Planner calls omit it unless the API rejects them."
        )
    if not secrets.get("GITHUB_TOKEN"):
        skipped.append(
            "GITHUB_TOKEN is unset. git push uses existing git credentials. "
            "Ask for GITHUB_TOKEN only if push fails for lack of auth."
        )

    skipped.append(
        "Browser logins are not checked here. If TikTok Creative Center, TikTok, or Instagram "
        "login expires during a pull, ask only for that login, skip that pull, and continue. "
        "Do not ask which regions or accounts to use."
    )

    _section("Blocked — ask for these, then skip only that step", blocked)
    print()
    _section("Skipped — optional, do not ask", skipped)
    print()
    if blocked:
        print("Result: a required item is missing. Ask only for the blocked items above.")
        return 1
    print("Result: nothing required is missing. Do not ask the user. Proceed with the fixed scope.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
