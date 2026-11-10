# -*- coding: utf-8 -*-
"""Repo paths and local configuration.

Account ids and secrets are not stored in the repo. Defaults come from
config/settings.example.yaml, then ~/.config/ai-meme-radar/settings.yaml
(or $AMR_CONFIG_DIR), then environment variables. Secrets are read only
from that folder's .env and from the environment.

Daily files live in one flat month folder: reports/2026-11/2026-11-10-daily-report.md.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"
EXAMPLE_SETTINGS = CONFIG_DIR / "settings.example.yaml"
LARK_SCHEMA = CONFIG_DIR / "lark-base-schema.json"
WATCHLIST = CONFIG_DIR / "watchlist.csv"

# Rebound from settings at import. Defaults are repo-relative.
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports"
TRACKER = DATA_DIR / "meme-daily-tracker.csv"
BACKTEST_JSON = DATA_DIR / "backtest-latest.json"
BACKTEST_CSV = DATA_DIR / "backtest-latest.csv"
LARK_BATCH_DIR = DATA_DIR / "lark-batches"
FONT = REPO_ROOT / "assets" / "fonts" / "NotoSansSC-Regular.otf"

_SECRET_KEYS = (
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GITHUB_TOKEN",
)
_LARK_TABLE_KEYS = (
    "cc_rank_snapshot",
    "cc_hashtag_curve",
    "cc_hashtag_audience",
    "meme_daily_tracker",
    "remix_videos",
    "backtest",
    "watchlist",
    "digest_index",
    "default_table",
)

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
    if DATA_DIR.is_dir():
        dirs.append(DATA_DIR)
    return dirs


def resolve(day: str, slug: str, *legacy_names: str) -> Path:
    """First existing candidate, else the canonical dated path.

    Canonical name is reports/YYYY-MM/YYYY-MM-DD-<slug>. Legacy names are
    the original filenames (meme_pack_2026-11-10.json and similar).
    """
    candidates = [dated(day, slug)]
    for name in legacy_names:
        candidates.append(month_dir(day) / name)
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


def _strip_comment(line: str) -> str:
    out = []
    quote = ""
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def _parse_simple_yaml(text: str) -> dict:
    """Nested YAML maps used by settings.example.yaml. No extra dependency."""
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        if ":" not in body:
            continue
        key, value = body.split(":", 1)
        key = key.strip()
        value = value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value == "":
            node: dict = {}
            parent[key] = node
            stack.append((indent, node))
            continue
        parent[key] = _coerce(value)
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
    if value == "{}":
        return {}
    if value == "":
        return ""
    return value


def config_dir() -> Path:
    override = os.environ.get("AMR_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "ai-meme-radar"


def _deep_merge(base: dict, overlay: dict) -> dict:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _repo_or(value, default: Path) -> Path:
    text = str(value or "").strip()
    if not text:
        return default
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _apply_env(cfg: dict) -> dict:
    lark = cfg.setdefault("lark", {})
    if os.environ.get("LARK_ENABLED", "").strip():
        lark["enabled"] = _coerce(os.environ["LARK_ENABLED"].strip())
    for env_name, key in (
        ("LARK_BASE_APP_TOKEN", "base_app_token"),
        ("LARK_BASE_URL", "base_url"),
        ("LARK_WIKI_PARENT_URL", "wiki_parent_url"),
        ("LARK_AUTHORIZED_BY", "authorized_by"),
    ):
        if os.environ.get(env_name, "").strip():
            lark[key] = os.environ[env_name].strip()
    tables = lark.setdefault("tables", {})
    for key in _LARK_TABLE_KEYS:
        env_name = "LARK_TABLE_" + key.upper()
        if os.environ.get(env_name, "").strip():
            tables[key] = os.environ[env_name].strip()
    ads = cfg.setdefault("google_ads", {})
    if os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "").strip():
        ads["customer_id"] = os.environ["GOOGLE_ADS_CUSTOMER_ID"].strip()
    paths = cfg.setdefault("paths", {})
    for env_name, key in (
        ("AMR_DATA_DIR", "data_dir"),
        ("AMR_REPORTS_DIR", "reports_dir"),
        ("AMR_REPORTLIB", "reportlib"),
        ("AMR_FONT", "font"),
    ):
        if os.environ.get(env_name, "").strip():
            paths[key] = os.environ[env_name].strip()
    return cfg


def load_settings() -> dict:
    """Example defaults, then local settings.yaml, then environment variables."""
    cfg: dict = {}
    if EXAMPLE_SETTINGS.exists():
        cfg = _parse_simple_yaml(EXAMPLE_SETTINGS.read_text(encoding="utf-8"))
    local = config_dir() / "settings.yaml"
    if local.exists():
        _deep_merge(cfg, _parse_simple_yaml(local.read_text(encoding="utf-8")))
    return _apply_env(cfg)


def _parse_env_file(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    if not path.exists():
        return found
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def merged_secrets() -> dict[str, str]:
    """Secrets from the local .env, overridden by the environment. Never from the repo."""
    found = _parse_env_file(config_dir() / ".env")
    for key in set(found) | set(_SECRET_KEYS):
        if os.environ.get(key, "").strip():
            found[key] = os.environ[key].strip()
    return found


def google_ads_secrets() -> dict[str, str]:
    env = merged_secrets()
    needed = ("GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN")
    missing = [key for key in needed if not env.get(key)]
    if missing:
        raise SystemExit(
            "Missing Google Ads secrets: "
            + ", ".join(missing)
            + f". Set them in {config_dir() / '.env'} or the environment."
        )
    return {key: env[key] for key in needed}


def google_ads_customer_id() -> str:
    return str((load_settings().get("google_ads") or {}).get("customer_id") or "").strip()


def require_google_ads_customer_id() -> str:
    value = google_ads_customer_id()
    if not value:
        raise SystemExit(
            "google_ads.customer_id is empty. Set it in "
            f"{config_dir() / 'settings.yaml'} or GOOGLE_ADS_CUSTOMER_ID."
        )
    return value


def lark_config() -> dict:
    lark = load_settings().get("lark") or {}
    if not isinstance(lark, dict):
        return {}
    return lark


def lark_enabled(sync_lark: bool = False, no_lark: bool = False) -> bool:
    """Default off. --sync-lark forces on, --no-lark forces off, else lark.enabled."""
    if sync_lark and no_lark:
        raise SystemExit("pass only one of --sync-lark and --no-lark")
    if no_lark:
        return False
    if sync_lark:
        return True
    return bool(lark_config().get("enabled"))


def lark_disabled_message() -> str:
    return (
        "Lark 同步默认关闭。日报写在 reports/YYYY-MM/ 并提交到仓库。"
        "要同步 Lark，把本地 settings.yaml 的 lark.enabled 设为 true，或运行时加 --sync-lark。"
    )


def require_lark_for_sync(table_keys: list[str] | None = None) -> dict:
    """Fail clearly when sync is on but account ids were left empty."""
    lark = lark_config()
    missing = []
    if not str(lark.get("base_app_token") or "").strip():
        missing.append("lark.base_app_token")
    if not str(lark.get("wiki_parent_url") or "").strip():
        missing.append("lark.wiki_parent_url")
    tables = lark.get("tables") or {}
    if not isinstance(tables, dict):
        tables = {}
    for key in table_keys or _LARK_TABLE_KEYS:
        if key == "default_table":
            continue
        if not str(tables.get(key) or "").strip():
            missing.append(f"lark.tables.{key}")
    if missing:
        raise SystemExit(
            "Lark sync is on but these settings are empty: "
            + ", ".join(missing)
            + f". Set them in {config_dir() / 'settings.yaml'} "
            + "(or LARK_BASE_APP_TOKEN, LARK_WIKI_PARENT_URL, LARK_TABLE_*)."
        )
    return lark


def lark_table_id(key: str) -> str:
    tables = lark_config().get("tables") or {}
    if not isinstance(tables, dict):
        return ""
    return str(tables.get(key) or "").strip()


def lark_digest_docs() -> dict[str, str]:
    docs = lark_config().get("digest_docs") or {}
    if not isinstance(docs, dict):
        return {}
    return {str(key): str(value or "").strip() for key, value in docs.items()}


def google_ads_env_file() -> Path:
    return config_dir() / ".env"


def google_ads_output_dir() -> Path:
    return REPO_ROOT / "research" / "output"


def reportlib_dir() -> Path:
    """Directory that contains the reportlib package. Default is scripts/."""
    settings = load_settings().get("paths") or {}
    return _repo_or(settings.get("reportlib"), REPO_ROOT / "scripts")


def prepare_reportlib() -> None:
    """Put scripts/ (or a settings override) on sys.path so `import reportlib` works."""
    folder = reportlib_dir()
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
        help="Force Lark sync off, including when local settings turn it on",
    )


def _bind_paths() -> None:
    global DATA_DIR, REPORTS_DIR, TRACKER, BACKTEST_JSON, BACKTEST_CSV, LARK_BATCH_DIR, FONT
    paths = load_settings().get("paths") or {}
    DATA_DIR = _repo_or(paths.get("data_dir"), REPO_ROOT / "data")
    REPORTS_DIR = _repo_or(paths.get("reports_dir"), REPO_ROOT / "reports")
    TRACKER = DATA_DIR / "meme-daily-tracker.csv"
    BACKTEST_JSON = DATA_DIR / "backtest-latest.json"
    BACKTEST_CSV = DATA_DIR / "backtest-latest.csv"
    LARK_BATCH_DIR = DATA_DIR / "lark-batches"
    FONT = _repo_or(paths.get("font"), REPO_ROOT / "assets" / "fonts" / "NotoSansSC-Regular.otf")


_bind_paths()
