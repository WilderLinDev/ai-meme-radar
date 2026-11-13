"""Deterministic text helpers: identity keys, entity refs, vocabulary matching."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

ENTITY_KINDS = ("trend", "format", "opportunity", "keyword", "site")
ASSESSABLE = ("trend", "opportunity")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_WORD = re.compile(r"[a-z0-9]+")
_ASCII = re.compile(r"^[\x00-\x7f]+$")


def norm_key(text: str) -> str:
    """Identity key for dedupe: NFKC, lowercase, alphanumerics only, single spaces.

    "AI Baby-Dance!" and "ai baby dance" share a key; word order matters.
    """
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = re.sub(r"[^\w]+", " ", t, flags=re.UNICODE).replace("_", " ")
    return " ".join(t.split())


def keyword_key(text: str) -> str:
    return norm_key(text)


def domain_of(value: str) -> str:
    v = (value or "").strip().lower()
    if not v:
        return ""
    if "://" not in v:
        v = "http://" + v
    host = urlparse(v).hostname or ""
    return host[4:] if host.startswith("www.") else host


def parse_ref(ref: str) -> tuple[str, str]:
    """'trend:ai-baby-dance' -> ('trend', 'ai-baby-dance'). Keywords and sites are normalized."""
    if ":" not in ref:
        raise ValueError(f"entity ref {ref!r} must look like kind:id")
    kind, _, ident = ref.partition(":")
    kind = kind.strip()
    if kind not in ENTITY_KINDS:
        raise ValueError(f"entity ref {ref!r}: kind must be one of {', '.join(ENTITY_KINDS)}")
    ident = ident.strip()
    if kind == "keyword":
        ident = keyword_key(ident)
    elif kind == "site":
        ident = domain_of(ident)
    elif not SLUG.match(ident):
        raise ValueError(f"entity ref {ref!r}: id must be kebab-case ascii")
    if not ident:
        raise ValueError(f"entity ref {ref!r} has an empty id")
    return kind, ident


def ref(kind: str, ident: str) -> str:
    return f"{kind}:{ident}"


class Vocabulary:
    """Word-boundary matching for ASCII terms, substring matching for CJK terms."""

    def __init__(self, terms: list[str]):
        ascii_terms = sorted({t for t in terms if _ASCII.match(t)}, key=len, reverse=True)
        self.cjk = sorted({t for t in terms if not _ASCII.match(t)})
        self.rx = re.compile(r"\b(" + "|".join(re.escape(t) for t in ascii_terms) + r")\b") if ascii_terms else None

    def hits(self, *texts: str | None) -> list[str]:
        blob = " ".join(t for t in texts if t).lower()
        found = set(self.rx.findall(blob)) if self.rx else set()
        found |= {t for t in self.cjk if t in blob}
        return sorted(found)


def tokens(text: str) -> set[str]:
    return set(_WORD.findall(norm_key(text)))


def term_matches(term: str, text: str) -> bool:
    """True when every word of `term` appears in `text` (order-free, for link suggestions)."""
    want = tokens(term)
    return bool(want) and want <= tokens(text)
