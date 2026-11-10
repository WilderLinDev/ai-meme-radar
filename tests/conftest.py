from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from radar.config import Layout, Settings

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "2026-11-10"
DAY = date(2026, 11, 10)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Layout:
    """A throwaway repo root holding the 2026-11-10 fixture in the real layout."""
    monkeypatch.setenv("AMR_CONFIG_DIR", str(tmp_path / "no-config"))
    (tmp_path / "config").mkdir()
    for name in ("watchlist.csv", "lark-base.json"):
        shutil.copy(REPO / "config" / name, tmp_path / "config" / name)
    (tmp_path / "data" / "raw").mkdir(parents=True)
    shutil.copy(REPO / "data" / "memes.csv", tmp_path / "data" / "memes.csv")
    shutil.copytree(FIXTURE / "raw", tmp_path / "data" / "raw" / DAY.isoformat())
    (tmp_path / "reports" / DAY.isoformat()).mkdir(parents=True)
    shutil.copy(FIXTURE / "judgments.json", tmp_path / "reports" / DAY.isoformat() / "judgments.json")
    return Layout.from_settings(tmp_path, Settings())
