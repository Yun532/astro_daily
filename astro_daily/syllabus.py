from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from astro_daily.seen import SeenStore

logger = logging.getLogger(__name__)


class WeekendSyllabusEntry(BaseModel):
    id: str
    series_id: str
    series_title_cn: str
    part_index: int = Field(ge=1)
    planned_parts: int = Field(ge=1)
    title_cn: str
    topic: str
    anchor_work_cn: str
    prerequisites_cn: list[str] = Field(default_factory=list)
    lesson_scope_cn: str
    previous_context_cn: str = ""
    why_classic_cn: str
    classic_paper_ids: list[str] = Field(default_factory=list)
    modern_directions_cn: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)

    @field_validator("id", "series_id", "series_title_cn", "title_cn", "topic", "anchor_work_cn", "lesson_scope_cn", "why_classic_cn")
    @classmethod
    def not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("weekend syllabus fields must not be empty")
        return value

    def to_prompt_topic(self) -> str:
        prerequisites = "；".join(self.prerequisites_cn) if self.prerequisites_cn else "从零基础讲起"
        papers = "；".join(self.classic_paper_ids) if self.classic_paper_ids else "按本讲主题选择经典工作"
        modern = "；".join(self.modern_directions_cn) if self.modern_directions_cn else "讲到当前常用模型和开放问题"
        return (
            f"STRICT_WEEKEND_SYLLABUS_LESSON id={self.id}; "
            f"series={self.series_title_cn} ({self.part_index}/{self.planned_parts}); "
            f"title={self.title_cn}; topic={self.topic}; "
            f"anchor={self.anchor_work_cn}; prerequisites={prerequisites}; "
            f"scope={self.lesson_scope_cn}; previous_context={self.previous_context_cn}; "
            f"why_classic={self.why_classic_cn}; classic_paper_ids={papers}; "
            f"modern_directions={modern}. "
            "Write it as a real course lecture for a beginner: start from foundations, build equations gradually, "
            "add reading exercises, figure-reading guidance, and clearly state what the next lesson will cover."
        )

    def seed_for_llm(self) -> dict[str, Any]:
        return self.model_dump()


def load_weekend_syllabus(path: Path) -> list[WeekendSyllabusEntry]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):
        raw = raw.get("lessons", [])
    if not isinstance(raw, list):
        raise ValueError(f"weekend syllabus must be a list or contain a lessons list: {path}")
    entries: list[WeekendSyllabusEntry] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            logger.warning("Ignoring malformed weekend syllabus entry %s in %s", index, path)
            continue
        try:
            entries.append(WeekendSyllabusEntry.model_validate(item))
        except ValueError as exc:
            logger.warning("Ignoring invalid weekend syllabus entry %s in %s: %s", index, path, exc)
    return entries


def select_next_weekend_lesson(path: Path, seen: SeenStore) -> WeekendSyllabusEntry | None:
    try:
        entries = load_weekend_syllabus(path)
    except ValueError as exc:
        logger.warning("Weekend syllabus could not be loaded: %s", exc)
        return None
    for entry in entries:
        if not _entry_seen(entry, seen):
            return entry
    return None


def _entry_seen(entry: WeekendSyllabusEntry, seen: SeenStore) -> bool:
    title_key = _normalize(entry.title_cn)
    for record in seen.records.values():
        if record.get("type") != "weekend_lesson":
            continue
        if _normalize(str(record.get("title", ""))) == title_key:
            return True
        if entry.series_id and record.get("series_id") == entry.series_id and record.get("part_index") == entry.part_index:
            return True
    return False


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())
