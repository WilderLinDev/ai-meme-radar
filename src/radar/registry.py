"""The meme registry (`data/memes.csv`): the only source of meme identity.

See docs/adr/0003. No fuzzy matching: an id that is not registered is an error.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator

from .csvio import DataError, read_rows, write_rows

PrimaryMetric = Literal["viralremix_new_videos", "x_posts", "cc_index_30d", "none"]
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
COLUMNS = ["id", "name", "name_zh", "aliases", "cc_hashtags", "primary_metric",
           "primary_region", "first_seen", "notes"]


def norm_hashtag(tag: str) -> str:
    return tag.strip().lstrip("#").strip().lower()


def _split(v) -> list[str]:
    if isinstance(v, list):
        return v
    return [x.strip() for x in str(v or "").split("|") if x.strip()]


class Meme(BaseModel):
    id: str
    name: str
    name_zh: str = ""
    aliases: list[str] = []
    cc_hashtags: list[str] = []
    primary_metric: PrimaryMetric
    primary_region: str = ""  # Creative Center region for cc_index_30d
    first_seen: date
    notes: str = ""

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("id must be lowercase kebab-case, e.g. shoulder-carry")
        return v

    @field_validator("aliases", mode="before")
    @classmethod
    def _aliases(cls, v):
        return _split(v)

    @field_validator("cc_hashtags", mode="before")
    @classmethod
    def _tags(cls, v):
        return [norm_hashtag(t) for t in _split(v)]

    @property
    def display(self) -> str:
        if self.name_zh and self.name_zh not in self.name:
            return f"{self.name}（{self.name_zh}）"
        return self.name

    def to_row(self) -> dict:
        d = self.model_dump()
        d["aliases"] = "|".join(self.aliases)
        d["cc_hashtags"] = "|".join(self.cc_hashtags)
        d["first_seen"] = self.first_seen.isoformat()
        return d


class Registry:
    def __init__(self, memes: list[Meme]):
        self.memes: dict[str, Meme] = {}
        problems = []
        for m in memes:
            if m.id in self.memes:
                problems.append(f"memes.csv: duplicate id {m.id}")
            self.memes[m.id] = m
        owner: dict[str, str] = {}
        for m in memes:
            if m.primary_metric == "cc_index_30d" and not (m.cc_hashtags and m.primary_region):
                problems.append(f"memes.csv: {m.id} uses cc_index_30d and needs cc_hashtags and primary_region")
            for t in m.cc_hashtags:
                if t in owner and owner[t] != m.id:
                    problems.append(f"memes.csv: #{t} is linked to both {owner[t]} and {m.id}")
                owner[t] = m.id
        if problems:
            raise DataError(problems)
        self.by_hashtag = owner

    @classmethod
    def load(cls, path: Path) -> "Registry":
        if not path.is_file():
            return cls([])
        return cls(read_rows(path, Meme))

    def save(self, path: Path) -> None:
        write_rows(path, COLUMNS, [m.to_row() for m in sorted(self.memes.values(), key=lambda m: m.id)])

    def __contains__(self, meme_id: str) -> bool:
        return meme_id in self.memes

    def __getitem__(self, meme_id: str) -> Meme:
        return self.memes[meme_id]

    def require(self, ids, where: str) -> None:
        unknown = sorted({i for i in ids if i not in self.memes})
        if unknown:
            raise DataError([f"{where}: meme id not in data/memes.csv: {', '.join(unknown)}"])
