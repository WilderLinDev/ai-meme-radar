# -*- coding: utf-8 -*-
"""Repo-relative paths and the optional Lark switch.

Daily files live in one flat month folder:

    reports/2026-11/2026-11-10-daily-report.md
    reports/2026-11/2026-11-10-meme-pack.json

Cumulative files live in data/. Original absolute paths (/workspace/lark,
/workspace/tiktok_cc, /home/box/.secrets) are checked only as fallbacks when
those directories still exist on the machine that used to run the routine.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports"
CONFIG_DIR = REPO_ROOT / "config"

TRACKER = DATA_DIR / "meme-daily-tracker.csv"
BACKTEST_JSON = DATA_DIR / "backtest-latest.json"
BACKTEST_CSV = DATA_DIR / "backtest-latest.csv"
LARK_BATCH_DIR = DATA_DIR / "lark-batches"
LARK_SCHEMA = CONFIG_DIR / "lark-base-schema.json"
WATCHLIST = CONFIG_DIR / "watchlist.csv"
SETTINGS_FILE = CONFIG_DIR / "settings.yaml"
FONT = REPO_ROOT / "assets" / "fonts" / "NotoSansSC-Regular.otf"

LEGACY_LARK = Path("/workspace/lark")
LEGACY_TIKTOK_CC = Path("/workspace/tiktok_cc")
LEGACY_SECRETS = Path("/home/box/.secrets/google_ads.env")

_PER_REGION_OLD = re.compile(r"^(\d{4}-\d{2}-\d{2})_([A-Z]{2})_([A-Za-z]+)_top100")
_PER_REGION_NEW = re.compile(r"^(\d{4}-\d{2}-\d{2})-cc-top100-([a-z]{2})\.csv$", re.I)


def month_dir(day: str) -> Path:
    """reports/YYYY-MM/ for a YYYY-MM-DD day. No year folder, no day folder."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day or ""):
        raise ValueError(f"expected YYYY-MM-DD, got {day!r}")
    return REPORTS_DIR / day[:7]


def dated(day: str, slug: str) -> Path:
    """reports/YYYY-MM/YYYY-MM-DD-<slug>."""
    return month_dir(day) / f"{day}-{slug}"


def search_dirs() -> list[Path]:
    dirs: list[Path] = []
    if REPORTS_DIR.is_dir():
        dirs.extend(sorted(p for p in REPORTS_DIR.iterdir() if p.is_dir()))
    for extra in (LEGACY_LARK, LEGACY_TIKTOK_CC, DATA_DIR):
        if extra.is_dir():
            dirs.append(extra)
    return dirs


def resolve(day: str, slug: str, *legacy_names: str) -> Path:
    """First existing candidate, else the canonical dated path.

    Canonical name is reports/YYYY-MM/YYYY-MM-DD-<slug>. Legacy names are
    the original filenames (meme_pack_2026-11-10.json and similar).
    """
    candidates = [dated(day, slug)]
    for name in legacy_names:
        candidates.append(month_dir(day) / name)
        candidates.append(LEGACY_LARK / name)
        candidates.append(LEGACY_TIKTOK_CC / name)
        candidates.append(DATA_DIR / name)
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def glob_many(*patterns: str) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for folder in search_dirs():
        for pattern in patterns:
            for path in folder.glob(pattern):
                if not path.is_file():
                    continue
                key = path.resolve()
                if key in seen:
                    continue
                seen.add(key)
                found.append(path)
    return sorted(found)


def parse_top100_filename(name: str, default_date: str) -> tuple[str, str, str]:
    """Return (date, region, industry) from a per-region Top 100 filename."""
    old = _PER_REGION_OLD.match(name)
    if old:
        return old.group(1), old.group(2).upper(), old.group(3)
    new = _PER_REGION_NEW.match(name)
    if new:
        return new.group(1), new.group(2).upper(), "NewsEnt"
    return default_date, "US", "NewsEnt"


def per_region_top100_files() -> list[Path]:
    """Per-region Creative Center lists only.

    Combined files (2026-11-10-cc-top100.csv, *_top100_all.csv) are skipped
    so a region is never guessed from a multi-region export.
    """
    found: list[Path] = []
    seen: set[Path] = set()
    for folder in search_dirs():
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if not path.is_file():
                continue
            if not (_PER_REGION_OLD.match(path.name) or _PER_REGION_NEW.match(path.name)):
                continue
            key = path.resolve()
            if key in seen:
                continue
            seen.add(key)
            found.append(path)
    return sorted(found)


def _parse_simple_yaml(text: str) -> dict:
    """Enough YAML for settings.example.yaml. No extra dependency."""
    root: dict = {}
    section: dict | None = None
    section_name = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith(" ") or line.startswith("\t"):
            if section is None or ":" not in line:
                continue
            key, value = line.strip().split(":", 1)
            section[key.strip()] = _coerce(value.strip())
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            section = {}
            section_name = key
            root[key] = section
            continue
        section = None
        root[key] = _coerce(value)
    if section_name and section is not None:
        root[section_name] = section
    return root


def _coerce(value: str):
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    lowered = value.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if value == "":
        return ""
    return value


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {"sync_lark": False}
    return _parse_simple_yaml(SETTINGS_FILE.read_text(encoding="utf-8"))


def lark_enabled(sync_lark: bool = False, no_lark: bool = False) -> bool:
    """Default off. --sync-lark forces on, --no-lark forces off, else settings."""
    if sync_lark and no_lark:
        raise SystemExit("pass only one of --sync-lark and --no-lark")
    if no_lark:
        return False
    if sync_lark:
        return True
    return bool(load_settings().get("sync_lark"))


def lark_disabled_message() -> str:
    return (
        "Lark 同步默认关闭。日报文件写在 reports/YYYY-MM/。"
        "需要生成 Lark Base 批次时加 --sync-lark，或在 config/settings.yaml 里设 sync_lark: true。"
    )


def google_ads_env_file() -> Path:
    override = os.environ.get("GOOGLE_ADS_ENV_FILE", "").strip()
    if override:
        return Path(override)
    settings = load_settings().get("google_ads") or {}
    configured = str(settings.get("env_file") or "").strip()
    if configured:
        return Path(configured)
    if LEGACY_SECRETS.exists():
        return LEGACY_SECRETS
    return Path.home() / ".secrets" / "google_ads.env"


def google_ads_output_dir() -> Path:
    return REPO_ROOT / "research" / "output"


def reportlib_dir() -> Path | None:
    settings = load_settings().get("paths") or {}
    configured = str(settings.get("reportlib") or "").strip()
    if configured:
        return Path(configured)
    if LEGACY_LARK.is_dir():
        return LEGACY_LARK
    return None


def prepare_reportlib() -> None:
    """Put the external reportlib package on sys.path when it is available."""
    folder = reportlib_dir()
    if folder and folder.is_dir():
        entry = str(folder)
        if entry not in sys.path:
            sys.path.insert(0, entry)


def add_lark_flags(parser) -> None:
    parser.add_argument(
        "--sync-lark",
        action="store_true",
        help="Turn Lark sync on for this run (default is off)",
    )
    parser.add_argument(
        "--no-lark",
        action="store_true",
        help="Force Lark sync off, including when settings.yaml turns it on",
    )
