"""Fixed research scope, the one settings loader, and the persistent data folder.

Every setting is read here and nowhere else. Precedence: environment variables > settings.toml >
defaults. settings.toml lives in `$AMR_CONFIG_DIR`, else `~/.config/ai-meme-radar/`, outside the repo.

    GEFEI_API_TOKEN   Ge Fei token (secret; overrides [gefei] token)
    AMR_CONFIG_DIR    folder holding settings.toml
    AMR_DATA_DIR      data folder (overrides [paths] data_dir; default ~/ai-meme-radar-data)
    AMR_REPORTS_DIR   report folder (overrides [paths] reports_dir; default <data>/reports)

Lark login belongs to lark-cli (`lark-cli auth login`); no Lark credential is stored here. The token
never appears in repr, logs or error messages (see `redact`).

    ai-meme-radar-data/
      radar.db                  the only research store (SQLite)
      run.lock                  single-instance lock for `run`
      reports/daily/            DAY.md
      reports/opportunities/    <opportunity-id>/DAY.md
      work/DAY/                 agent inputs for the day (research.json, assessments.json)
      feedback/                 human feedback files (*.json), applied once each
"""
from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

# ---- fixed scope (never ask the user to change these) ----
PRIMARY_MARKET = "US"
SUPPLEMENTARY_MARKETS = ("GB", "CA", "AU")
OBSERVED_MARKETS = ("DE", "JP", "KR", "FR")
GLOBAL_MARKET = "WORLD"  # early signals
MARKETS = (PRIMARY_MARKET, *SUPPLEMENTARY_MARKETS, *OBSERVED_MARKETS, GLOBAL_MARKET)
CC_REGIONS = ("US", "GB", "AU", "CA", "DE", "JP", "KR", "FR")  # Creative Center: NL is not offered
SOCIAL_PLATFORMS = ("TikTok", "CapCut", "Instagram", "X", "YouTube", "Reddit")  # never Douyin
# Every social source the agent must report on each day in research.json `social_coverage`.
COVERAGE_SOURCES = (*SOCIAL_PLATFORMS, "Creative Center", "Watchlist")

GEFEI_BASE_URL = "https://seo.web.cafe"


_clock: Callable[[], datetime] | None = None  # tests install a fake clock with set_clock()


def set_clock(fn: Callable[[], datetime] | None) -> None:
    global _clock
    _clock = fn


def now() -> datetime:
    """Wall-clock time in Asia/Shanghai. Every ingestion timestamp comes from here."""
    return _clock() if _clock else datetime.now(TZ)


def today() -> date:
    return now().date()


def end_of(day: date) -> str:
    """The historical cutoff of a report day: its last second, as an ingestion timestamp to compare with."""
    return datetime.combine(day, time(23, 59, 59), TZ).isoformat()


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


# Environment variables that override settings.toml (the only env vars the app reads).
ENV_CONFIG_DIR = "AMR_CONFIG_DIR"
ENV_DATA_DIR = "AMR_DATA_DIR"
ENV_REPORTS_DIR = "AMR_REPORTS_DIR"
ENV_TOKEN = "GEFEI_API_TOKEN"


class ConfigError(RuntimeError):
    pass


def _env(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def config_dir(env: Mapping[str, str] | None = None) -> Path:
    v = _env(os.environ if env is None else env, ENV_CONFIG_DIR)
    return Path(v).expanduser() if v else Path.home() / ".config" / "ai-meme-radar"


@dataclass
class GefeiSettings:
    token: str = field(default="", repr=False)  # secret: never printed
    base_url: str = GEFEI_BASE_URL
    keyword_detail_limit: int = 40  # keyword_detail calls per sync for creative-relevant new keywords
    refresh_days: int = 3  # batches finished within this many days are re-fetched (content may update)


@dataclass
class LarkSettings:
    """Lark login is lark-cli's own (`lark-cli auth login`); no Lark credentials live here."""
    enabled: bool = False
    daily_parent: str = ""  # Wiki node token (or folder token) that daily reports go under
    opportunity_parent: str = ""  # same for in-depth reports; empty = daily_parent
    identity: str = "user"  # lark-cli --as user|bot
    cli: str = "lark-cli"


@dataclass
class Settings:
    gefei: GefeiSettings = field(default_factory=GefeiSettings)
    lark: LarkSettings = field(default_factory=LarkSettings)
    data_dir: str = ""
    reports_dir: str = ""
    source: Path | None = None  # the settings.toml that was read, if any
    token_from: str = ""  # "env", "toml" or "" (where the token came from; never the value)

    @property
    def token(self) -> str:
        return self.gefei.token

    def require_token(self) -> str:
        if not self.gefei.token:
            raise ConfigError(f"Ge Fei API token missing: set ${ENV_TOKEN} or [gefei] token in "
                              f"{self.source or config_dir() / 'settings.toml'}")
        return self.gefei.token

    def redact(self, text: str) -> str:
        return redact(text, self.gefei.token)


def redact(text: str, *secrets: str) -> str:
    """Remove secrets and bearer headers from any text before it is printed or stored."""
    out = str(text)
    for sec in secrets:
        if sec and len(sec) >= 4:
            out = out.replace(sec, "***")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+", r"\1***", re.sub(r"wc_mcp_[A-Za-z0-9_\-]+", "wc_mcp_***", out))


def _section(raw: dict, name: str, path: Path) -> dict:
    v = raw.get(name) or {}
    if not isinstance(v, dict):
        raise ConfigError(f"{path}: [{name}] must be a table")
    return v


def load_settings(path: Path | None = None, env: Mapping[str, str] | None = None) -> Settings:
    """The one settings loader. Precedence: environment variables > settings.toml > defaults.

    settings.toml lives in $AMR_CONFIG_DIR, else ~/.config/ai-meme-radar/. A missing file is fine
    (all defaults); a malformed one is an error that names the file and key, never a value.
    """
    env = os.environ if env is None else env
    path = path or config_dir(env) / "settings.toml"
    raw: dict = {}
    if path.is_file():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: invalid TOML ({e})") from None
    g, lk, p = _section(raw, "gefei", path), _section(raw, "lark", path), _section(raw, "paths", path)
    try:
        s = Settings(
            gefei=GefeiSettings(
                token=str(g.get("token", "")).strip(),
                base_url=str(g.get("base_url", GEFEI_BASE_URL)).rstrip("/"),
                keyword_detail_limit=int(g.get("keyword_detail_limit", 40)),
                refresh_days=int(g.get("refresh_days", 3)),
            ),
            lark=LarkSettings(
                enabled=bool(lk.get("enabled", False)),
                daily_parent=str(lk.get("daily_parent", "")),
                opportunity_parent=str(lk.get("opportunity_parent", "")),
                identity=str(lk.get("identity", "user")),
                cli=str(lk.get("cli", "lark-cli")),
            ),
            data_dir=str(p.get("data_dir", "")),
            reports_dir=str(p.get("reports_dir", "")),
            source=path if path.is_file() else None,
        )
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{path}: wrong value type ({type(e).__name__})") from None
    s.token_from = "toml" if s.gefei.token else ""
    if _env(env, ENV_TOKEN):
        s.gefei.token, s.token_from = _env(env, ENV_TOKEN), "env"
    if _env(env, ENV_DATA_DIR):
        s.data_dir = _env(env, ENV_DATA_DIR)
    if _env(env, ENV_REPORTS_DIR):
        s.reports_dir = _env(env, ENV_REPORTS_DIR)
    return s


@dataclass
class Paths:
    root: Path
    reports_root: Path | None = None  # default <root>/reports

    @classmethod
    def resolve(cls, settings: Settings) -> "Paths":
        """Settings already carry env overrides; nothing else reads the environment."""
        root = Path(settings.data_dir).expanduser() if settings.data_dir else Path.home() / "ai-meme-radar-data"
        reports = Path(settings.reports_dir).expanduser() if settings.reports_dir else None
        return cls(root, reports)

    @property
    def reports(self) -> Path:
        return self.reports_root or self.root / "reports"

    @property
    def db(self) -> Path:
        return self.root / "radar.db"

    @property
    def lock(self) -> Path:
        return self.root / "run.lock"

    def daily_report(self, day: date) -> Path:
        return self.reports / "daily" / f"{day.isoformat()}.md"

    def opportunity_report(self, opp_id: str, day: date) -> Path:
        return self.reports / "opportunities" / opp_id / f"{day.isoformat()}.md"

    def work(self, day: date) -> Path:
        return self.root / "work" / day.isoformat()

    @property
    def feedback_inbox(self) -> Path:
        return self.root / "feedback"

    def ensure(self) -> None:
        for p in (self.reports / "daily", self.reports / "opportunities", self.root / "work", self.feedback_inbox):
            p.mkdir(parents=True, exist_ok=True)


REPO = Path(__file__).resolve().parents[2]


def research_terms() -> dict[str, list[str]]:
    """Creative-relevance vocabulary used to pre-filter Ge Fei data (config/research.toml)."""
    path = REPO / "config" / "research.toml"
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {k: [str(t).lower() for t in v] for k, v in raw.items() if isinstance(v, list)}
