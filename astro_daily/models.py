from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


IACT_PHRASES = (
    "imaging atmospheric cherenkov telescope",
    "atmospheric cherenkov",
    "cherenkov telescope array",
    "h.e.s.s.",
    "大气切伦科夫望远镜",
)

IACT_ACRONYMS = {"iact", "cta", "magic", "hess", "veritas", "lst", "sst", "mst"}


class Paper(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    url: str
    pdf_url: str | None = None
    source: str
    category: str | None = None
    published: datetime | None = None
    updated: datetime | None = None
    journal: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("paper_id", "title", "url", "source")
    @classmethod
    def not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value

    @field_validator("abstract", mode="before")
    @classmethod
    def normalize_abstract(cls, value: Any) -> str:
        if value is None:
            return ""
        return " ".join(str(value).split())

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: Any) -> str:
        return " ".join(str(value).split())

    @property
    def is_high_energy(self) -> bool:
        return self.category == "astro-ph.HE"

    @property
    def is_priority_topic(self) -> bool:
        if self.is_high_energy:
            return True
        text = " ".join([self.title, self.abstract, " ".join(self.tags)]).casefold()
        if any(phrase in text for phrase in IACT_PHRASES):
            return True
        tokens = set(re.findall(r"[a-z0-9]+", text))
        return bool(tokens & IACT_ACRONYMS)


class PaperScore(BaseModel):
    novelty_score: int = Field(ge=1, le=10)
    importance_score: int = Field(ge=1, le=10)
    relevance_to_me: int = Field(ge=1, le=10)
    final_score: float = Field(ge=0, le=10)
    keep: bool
    reason: str


class PaperSummary(BaseModel):
    paper_id: str
    title_cn: str
    summary_cn: str
    why_important_cn: str
    value_cn: str
    why_care_cn: str
    background_cn: str = ""
    basic_theory_cn: str = ""
    figures_to_check_cn: str = ""
    related_work_cn: str = ""
    similar_work_links: list[str] = Field(default_factory=list)
    foundational_work_links: list[str] = Field(default_factory=list)
    tension_or_opposing_links: list[str] = Field(default_factory=list)


class ScoredPaper(BaseModel):
    paper: Paper
    score: PaperScore
    summary: PaperSummary | None = None


class ScoreResult(PaperScore):
    paper_id: str


class ScoreBatch(BaseModel):
    scores: list[ScoreResult]


class SummaryBatch(BaseModel):
    summaries: list[PaperSummary]
