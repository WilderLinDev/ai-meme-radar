"""Fixed scope, local settings, and where every file lives.

Settings come from `settings.toml` in the local config folder
(`$AMR_CONFIG_DIR`, else `~/.config/ai-meme-radar/`). The repo only ships
`config/settings.example.toml`. Nothing secret is read: Lark writes go through
the user's connector, and git push uses existing git credentials.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# ---- fixed scope (never ask the user to change these) ----
CC_REGIONS = ("US", "GB", "AU", "CA", "DE", "JP", "KR", "FR")
CC_PERIODS = (7, 30)
CC_INDUSTRY = "News & Entertainment"
PLATFORMS = ("TikTok", "CapCut", "Instagram")
BACKTEST_HORIZON_DAYS = 3
MISSED_RISE_THRESHOLD = 0.20  # watch/skip memes rising >= 20% by D+3 count as missed
SHARE_MIN_N = 5


def config_dir() -> Path:
    env = os.environ.get("AMR_CONFIG_DIR", "").strip()
    return Path(env).expanduser() if env else Path.home() / ".config" / "ai-meme-radar"


@dataclass
class LarkSettings:
    enabled: bool = False
    base_app_token: str = ""
    base_url: str = ""
    wiki_parent_url: str = ""
    authorized_by: str = ""
    tables: dict[str, str] = field(default_factory=dict)
    digest_docs: dict[str, str] = field(default_factory=dict)


@dataclass
class Settings:
    lark: LarkSettings = field(default_factory=LarkSettings)
    data_dir: str = ""
    reports_dir: str = ""
    font: str = ""
    source: Path | None = None  # the settings.toml that was read, if any


def load_settings(path: Path | None = None) -> Settings:
    path = path or config_dir() / "settings.toml"
    if not path.is_file():
        return Settings()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    lark = raw.get("lark") or {}
    paths = raw.get("paths") or {}
    return Settings(
        lark=LarkSettings(
            enabled=bool(lark.get("enabled", False)),
            base_app_token=str(lark.get("base_app_token", "")),
            base_url=str(lark.get("base_url", "")),
            wiki_parent_url=str(lark.get("wiki_parent_url", "")),
            authorized_by=str(lark.get("authorized_by", "")),
            tables={k: str(v) for k, v in (lark.get("tables") or {}).items()},
            digest_docs={k: str(v) for k, v in (lark.get("digest_docs") or {}).items()},
        ),
        data_dir=str(paths.get("data_dir", "")),
        reports_dir=str(paths.get("reports_dir", "")),
        font=str(paths.get("font", "")),
        source=path,
    )


@dataclass
class Layout:
    """Every path the pipeline reads or writes. See docs/adr/0002."""

    root: Path
    data: Path
    reports: Path
    font: Path

    @classmethod
    def from_settings(cls, root: Path, settings: Settings) -> "Layout":
        def pick(value: str, default: Path) -> Path:
            if not value:
                return default
            p = Path(value).expanduser()
            return p if p.is_absolute() else root / p

        return cls(
            root=root,
            data=pick(settings.data_dir, root / "data"),
            reports=pick(settings.reports_dir, root / "reports"),
            font=pick(settings.font, root / "assets" / "fonts" / "NotoSansSC-Regular.otf"),
        )

    # raw evidence, written once per day
    def raw_dir(self, day: date) -> Path:
        return self.data / "raw" / day.isoformat()

    def raw_days(self) -> list[date]:
        base = self.data / "raw"
        if not base.is_dir():
            return []
        out = []
        for p in base.iterdir():
            try:
                out.append(date.fromisoformat(p.name))
            except ValueError:
                continue
        return sorted(out)

    # derived history
    @property
    def registry(self) -> Path:
        return self.data / "memes.csv"

    @property
    def tracker(self) -> Path:
        return self.data / "tracker.csv"

    @property
    def backtest_json(self) -> Path:
        return self.data / "backtest.json"

    @property
    def backtest_csv(self) -> Path:
        return self.data / "backtest.csv"

    def lark_batches(self, day: date) -> Path:
        return self.data / "lark-batches" / day.isoformat()

    # deliverables
    def report_dir(self, day: date) -> Path:
        return self.reports / day.isoformat()

    def judgments(self, day: date) -> Path:
        return self.report_dir(day) / "judgments.json"

    def pack(self, day: date) -> Path:
        return self.report_dir(day) / "meme-pack.json"

    # static config
    @property
    def watchlist(self) -> Path:
        return self.root / "config" / "watchlist.csv"

    @property
    def lark_schema(self) -> Path:
        return self.root / "config" / "lark-base.json"
