"""Fixed research scope, local settings, and the persistent data folder.

Settings come from `settings.toml` in the local config folder (`$AMR_CONFIG_DIR`,
else `~/.config/ai-meme-radar/`). Secrets (the Ge Fei token) live there or in
`$GEFEI_API_TOKEN`; never in the repo.

All research data lives in one folder outside the Git checkout (`$AMR_DATA_DIR`,
else `[paths] data_dir`, else `~/ai-meme-radar-data`), so it survives pulls,
branch switches and code updates:

    ai-meme-radar-data/
      radar.db                  the only research store (SQLite)
      reports/daily/            DAY.md
      reports/opportunities/    <opportunity-id>/DAY.md
      work/DAY/                 agent inputs for the day (research.json, assessments.json)
      feedback/                 human feedback files (*.json), applied once each
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
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

GEFEI_BASE_URL = "https://seo.web.cafe"


def today() -> date:
    return datetime.now(TZ).date()


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def config_dir() -> Path:
    env = os.environ.get("AMR_CONFIG_DIR", "").strip()
    return Path(env).expanduser() if env else Path.home() / ".config" / "ai-meme-radar"


@dataclass
class GefeiSettings:
    token: str = ""
    base_url: str = GEFEI_BASE_URL
    keyword_detail_limit: int = 40  # keyword_detail calls per sync for creative-relevant new keywords
    refresh_days: int = 3  # batches finished within this many days are re-fetched (content may update)


@dataclass
class LarkSettings:
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
    source: Path | None = None

    @property
    def token(self) -> str:
        return os.environ.get("GEFEI_API_TOKEN", "").strip() or self.gefei.token


def load_settings(path: Path | None = None) -> Settings:
    path = path or config_dir() / "settings.toml"
    if not path.is_file():
        return Settings()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    g, lk, p = raw.get("gefei") or {}, raw.get("lark") or {}, raw.get("paths") or {}
    return Settings(
        gefei=GefeiSettings(
            token=str(g.get("token", "")),
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
        source=path,
    )


@dataclass
class Paths:
    root: Path

    @classmethod
    def resolve(cls, settings: Settings) -> "Paths":
        env = os.environ.get("AMR_DATA_DIR", "").strip()
        raw = env or settings.data_dir
        return cls(Path(raw).expanduser() if raw else Path.home() / "ai-meme-radar-data")

    @property
    def db(self) -> Path:
        return self.root / "radar.db"

    def daily_report(self, day: date) -> Path:
        return self.root / "reports" / "daily" / f"{day.isoformat()}.md"

    def opportunity_report(self, opp_id: str, day: date) -> Path:
        return self.root / "reports" / "opportunities" / opp_id / f"{day.isoformat()}.md"

    def work(self, day: date) -> Path:
        return self.root / "work" / day.isoformat()

    @property
    def feedback_inbox(self) -> Path:
        return self.root / "feedback"

    def ensure(self) -> None:
        for p in (self.root / "reports" / "daily", self.root / "reports" / "opportunities",
                  self.root / "work", self.feedback_inbox):
            p.mkdir(parents=True, exist_ok=True)


REPO = Path(__file__).resolve().parents[2]


def research_terms() -> dict[str, list[str]]:
    """Creative-relevance vocabulary used to pre-filter Ge Fei data (config/research.toml)."""
    path = REPO / "config" / "research.toml"
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {k: [str(t).lower() for t in v] for k, v in raw.items() if isinstance(v, list)}
