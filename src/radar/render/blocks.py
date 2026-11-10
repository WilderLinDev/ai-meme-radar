"""A tiny document model. `document.py` builds it; `markdown.py` and `docx.py` write it.

Both outputs come from the same blocks, so the Markdown and Word reports
cannot say different things.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Link:
    text: str
    url: str


@dataclass(frozen=True)
class Ref:
    """A jump to an anchor inside the same report."""
    text: str
    anchor: str


Inline = str | Link | Ref


@dataclass
class Heading:
    level: int
    text: str
    anchor: str | None = None


@dataclass
class Para:
    text: str
    muted: bool = False


@dataclass
class Bullets:
    items: list[tuple[str | None, Inline]]  # (bold prefix, content)


@dataclass
class Table:
    headers: list[str]
    rows: list[list[Inline]]
    caption: str = ""


@dataclass
class Card:
    """Key/value conclusion card. `tone` is the verdict, for shading."""
    rows: list[tuple[str, str]]
    tone: str = ""


@dataclass
class Image:
    path: Path
    caption: str = ""


@dataclass
class Code:
    text: str


Block = Heading | Para | Bullets | Table | Card | Image | Code


@dataclass
class Document:
    title: str
    subtitle: str
    blocks: list[Block] = field(default_factory=list)

    def add(self, *blocks: Block) -> None:
        self.blocks.extend(blocks)
