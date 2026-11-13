"""Shapes of the files the agent (and humans) write. Validation lives here.

* `work/DAY/research.json`  trends, formats, opportunities, links, evidence, gaps
* `work/DAY/assessments.json`  one assessment per trend / opportunity judged today
* `feedback/*.json`  human changes to decisions, priorities, links, direction
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..text import ASSESSABLE, SLUG, parse_ref

Channel = Literal["social", "search", "product", "market"]
Confidence = Literal["high", "medium", "low"]
Tag = Literal["已核实", "第三方读数", "估算"]
Lifecycle = Literal["early_signal", "emerging", "proven", "fading"]
Decision = Literal["build", "validate", "monitor", "skip"]
Priority = Literal["P0", "P1", "P2", "P3"]
Level = Literal["high", "medium", "low", "unknown"]
Direction = Literal["rising", "holding", "falling"]
ProductType = Literal["video", "image", "audio", "effect", "multi", "other"]

DIMENSIONS = ("social_momentum", "search_demand", "audience_participation", "template_potential",
              "ai_feasibility", "competition", "timing")
DEEP_SECTIONS = ("trend_overview", "why_now", "social_evidence", "search_demand", "audience_behavior",
                 "format_analysis", "product_opportunity", "competition", "ai_feasibility", "recommendation",
                 "evidence_confidence", "remaining_questions")
RELATIONS = {
    ("trend", "format"): {"uses"},
    ("format", "opportunity"): {"enables"},
    ("trend", "opportunity"): {"drives"},
    ("trend", "keyword"): {"searched_as"},
    ("opportunity", "keyword"): {"targets"},
    ("trend", "site"): {"competitor", "related"},
    ("format", "site"): {"competitor", "related"},
    ("opportunity", "site"): {"competitor", "related"},
    ("trend", "trend"): {"related", "variant_of"},
    ("format", "format"): {"related", "variant_of"},
}


def check_link(src: str, dst: str, relation: str) -> tuple[str, str]:
    """The one rule for links, used by research files and human feedback alike.

    Both refs must parse, and (src kind, dst kind, relation) must be in RELATIONS, in that direction.
    Returns the normalized refs.
    """
    sk, si = parse_ref(src)
    dk, di = parse_ref(dst)
    allowed = RELATIONS.get((sk, dk))
    if not allowed or relation not in allowed:
        opts = sorted(f"{a}->{b}:{'|'.join(sorted(r))}" for (a, b), r in RELATIONS.items())
        raise ValueError(f"link {src} -[{relation}]-> {dst} not allowed; allowed: {opts}")
    if (sk, si) == (dk, di):
        raise ValueError(f"link {src} -> {dst} points at itself")
    return f"{sk}:{si}", f"{dk}:{di}"


def split_link_value(value: str) -> tuple[str, str]:
    """Feedback link value 'relation->kind:id' -> (relation, target ref)."""
    relation, sep, target = value.partition("->")
    if not sep or not relation.strip() or not target.strip():
        raise ValueError("link feedback value must look like 'relation->kind:id'")
    return relation.strip(), target.strip()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Node(Strict):
    id: str
    name: str

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG.match(v):
            raise ValueError(f"id {v!r} must be kebab-case ascii, e.g. ai-baby-dance")
        return v


class TrendIn(Node):
    summary: str = ""
    aliases: list[str] = []
    search_terms: list[str] = []  # English queries a searcher would type; drives search-demand research
    regions: list[str] = []
    platforms: list[str] = []
    origin: str = ""


class FormatIn(Node):
    description: str = ""
    user_input: str = ""  # what the user uploads / types
    output: str = ""  # what they get back
    aliases: list[str] = []


class OpportunityIn(Node):
    description: str = ""
    product_type: ProductType = "video"
    aliases: list[str] = []
    search_terms: list[str] = []


class LinkIn(Strict):
    src: str = Field(alias="from")
    dst: str = Field(alias="to")
    relation: str
    note: str = ""

    @model_validator(mode="after")
    def _check(self):
        check_link(self.src, self.dst, self.relation)
        return self


class EvidenceIn(Strict):
    ref: str = ""  # day-scoped handle so assessments can cite it
    entity: str
    channel: Channel
    source: str  # TikTok, CapCut, Creative Center, Google Trends (Ge Fei), ...
    url: str = ""
    metric: str = ""  # views, posts, cc_index, search_volume, heat_ratio, ... (empty for qualitative)
    value: float | None = None
    unit: str = ""
    region: str = ""
    sample_size: int | None = None
    metric_definition: str = ""
    collected_at: datetime
    confidence: Confidence
    tag: Tag
    api_call_id: int | None = None
    note: str = ""

    @field_validator("entity")
    @classmethod
    def _entity(cls, v):
        parse_ref(v)
        return v

    @model_validator(mode="after")
    def _numbers(self):
        if self.value is not None and not self.metric:
            raise ValueError(f"evidence {self.ref or self.entity}: a value needs a metric name")
        if self.value is not None and not self.metric_definition:
            raise ValueError(f"evidence {self.ref or self.entity}: metric {self.metric} needs metric_definition")
        if self.collected_at.tzinfo is None:
            raise ValueError(f"evidence {self.ref or self.entity}: collected_at needs a timezone offset")
        return self


class GapIn(Strict):
    source: str
    note: str


class ResearchFile(Strict):
    day: date
    trends: list[TrendIn] = []
    formats: list[FormatIn] = []
    opportunities: list[OpportunityIn] = []
    links: list[LinkIn] = []
    evidence: list[EvidenceIn] = []
    gaps: list[GapIn] = []
    notes: str = ""

    @model_validator(mode="after")
    def _unique(self):
        problems = []
        for kind, items in (("trend", self.trends), ("format", self.formats), ("opportunity", self.opportunities)):
            ids = [i.id for i in items]
            problems += [f"duplicate {kind} id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
        refs = [e.ref for e in self.evidence if e.ref]
        problems += [f"duplicate evidence ref {r}" for r in sorted({r for r in refs if refs.count(r) > 1})]
        if problems:
            raise ValueError("; ".join(problems))
        return self


class DimensionIn(Strict):
    level: Level
    note: str
    evidence: list[str] = []  # evidence refs (any day) or "call:<api_call_id>"


class TrackedSeries(Strict):
    """The one series backtests judge. Fixed at assessment time."""
    kind: Literal["evidence", "keyword_heat"]
    entity: str = ""  # evidence: whose evidence (defaults to the assessed entity)
    metric: str = ""  # evidence: metric name
    region: str = ""
    source: str = ""
    keyword: str = ""  # keyword_heat: Ge Fei keyword (heat_ratio series)

    @model_validator(mode="after")
    def _check(self):
        if self.kind == "evidence" and not self.metric:
            raise ValueError("tracked evidence series needs a metric")
        if self.kind == "keyword_heat" and not self.keyword:
            raise ValueError("tracked keyword_heat series needs a keyword")
        return self


class AssessmentIn(Strict):
    entity: str
    lifecycle: Lifecycle
    decision: Decision
    priority: Priority
    confidence: Confidence
    dimensions: dict[str, DimensionIn]
    summary: str  # one line for the daily report
    rationale: str
    why_now: str = ""
    assumptions: list[str] = []  # inferences and unvalidated assumptions
    open_questions: list[str] = []
    next_steps: list[str] = []
    expected_direction: Direction | None = None  # defaults from lifecycle
    tracked: TrackedSeries | None = None
    deep: dict[str, str] = {}  # in-depth report sections (DEEP_SECTIONS), opportunities only
    facts: dict | None = None  # scaffold copy of computed metrics; ignored on ingest
    carried_from: str | None = None  # scaffold marker; ignored on ingest

    @field_validator("entity")
    @classmethod
    def _entity(cls, v):
        kind, _ = parse_ref(v)
        if kind not in ASSESSABLE:
            raise ValueError(f"{v}: only {', '.join(ASSESSABLE)} are assessed")
        return v

    @model_validator(mode="after")
    def _dims(self):
        missing = [d for d in DIMENSIONS if d not in self.dimensions]
        extra = [d for d in self.dimensions if d not in DIMENSIONS]
        if missing or extra:
            raise ValueError(f"{self.entity}: dimensions missing {missing} / unknown {extra}")
        bad = [k for k in self.deep if k not in DEEP_SECTIONS]
        if bad:
            raise ValueError(f"{self.entity}: unknown deep sections {bad}; allowed {list(DEEP_SECTIONS)}")
        if self.deep and not self.entity.startswith("opportunity:"):
            raise ValueError(f"{self.entity}: deep reports are written for opportunities only")
        return self


class AssessmentFile(Strict):
    day: date
    assessments: list[AssessmentIn]
    notes: str = ""

    @model_validator(mode="after")
    def _unique(self):
        ents = [a.entity for a in self.assessments]
        dup = sorted({e for e in ents if ents.count(e) > 1})
        if dup:
            raise ValueError(f"duplicate assessments for {dup}")
        return self


class FeedbackIn(Strict):
    entity: str
    field: Literal["decision", "priority", "lifecycle", "link_add", "link_remove", "direction"]
    value: str  # new decision/priority/lifecycle; "relation->kind:id" for links; free text for direction
    reason: str
    author: str
    at: datetime

    @model_validator(mode="after")
    def _check(self):
        parse_ref(self.entity)
        allowed = {"decision": Decision, "priority": Priority, "lifecycle": Lifecycle}.get(self.field)
        if allowed and self.value not in allowed.__args__:
            raise ValueError(f"feedback {self.field}={self.value!r} must be one of {allowed.__args__}")
        if self.field in ("link_add", "link_remove"):
            relation, target = split_link_value(self.value)
            check_link(self.entity, target, relation)
        if not self.reason.strip():
            raise ValueError("feedback needs a reason")
        if self.at.tzinfo is None:
            raise ValueError("feedback `at` needs a timezone offset")
        return self


class FeedbackFile(Strict):
    feedback: list[FeedbackIn]


DEFAULT_DIRECTION: dict[str, Direction] = {
    "early_signal": "rising", "emerging": "rising", "proven": "holding", "fading": "falling"}
