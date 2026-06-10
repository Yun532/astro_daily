from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from astro_daily.models import Paper, WeekendLesson

logger = logging.getLogger(__name__)


class SeenStore:
    def __init__(self, path: Path, records: dict[str, dict[str, Any]] | None = None):
        self.path = path
        self.records = records or {}

    @classmethod
    def load(cls, path: Path) -> "SeenStore":
        if not path.exists():
            return cls(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Could not parse %s: %s", path, exc)
            return cls(path)
        if not isinstance(raw, dict):
            logger.warning("Ignoring malformed seen file %s", path)
            return cls(path)
        return cls(path, {str(key): value for key, value in raw.items() if isinstance(value, dict)})

    def is_seen(self, paper: Paper) -> bool:
        return (
            paper.paper_id in self.records
            or _title_key(paper) in self.records
            or _loose_title_key(paper) in self.records
        )

    def filter_new(self, papers: list[Paper]) -> list[Paper]:
        return [paper for paper in papers if not self.is_seen(paper)]

    def mark_many(self, papers: list[Paper], *, seen_date: date) -> None:
        for paper in papers:
            self.records[paper.paper_id] = {
                "type": "paper",
                "title": paper.title,
                "url": paper.url,
                "source": paper.source,
                "category": paper.category,
                "first_seen": seen_date.isoformat(),
            }
            self.records[_title_key(paper)] = {
                "type": "paper_title",
                "paper_id": paper.paper_id,
                "first_seen": seen_date.isoformat(),
            }
            loose_title_key = _loose_title_key(paper)
            if loose_title_key:
                self.records[loose_title_key] = {
                    "type": "paper_title_loose",
                    "paper_id": paper.paper_id,
                    "first_seen": seen_date.isoformat(),
                }

    def mark_lessons(self, lessons: list[WeekendLesson], *, seen_date: date) -> None:
        for lesson in lessons:
            record = {
                "type": "weekend_lesson",
                "topic": lesson.topic,
                "title": lesson.title_cn,
                "anchor_work": lesson.anchor_work_cn,
                "series_id": lesson.series_id,
                "series_title": lesson.series_title_cn,
                "part_index": lesson.part_index,
                "planned_parts": lesson.planned_parts,
                "lesson_scope": lesson.lesson_scope_cn,
                "next_lesson_suggestions": lesson.next_lesson_suggestions_cn,
                "first_seen": seen_date.isoformat(),
                "search_keywords": lesson.search_keywords,
                "links": lesson.links,
            }
            self.records[_lesson_title_key(lesson.title_cn)] = record
            anchor_key = _lesson_anchor_key(lesson.anchor_work_cn)
            if anchor_key:
                self.records[anchor_key] = record

    def weekend_lesson_history(self, *, limit: int = 12) -> list[dict[str, str]]:
        lessons: list[dict[str, str]] = []
        seen_titles: set[str] = set()
        records = sorted(self.records.values(), key=lambda record: str(record.get("first_seen", "")), reverse=True)
        for record in records:
            if record.get("type") != "weekend_lesson":
                continue
            title = str(record.get("title", "")).strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            item = {
                "title": title,
                "topic": str(record.get("topic", "")).strip(),
                "anchor_work": str(record.get("anchor_work", "")).strip(),
            }
            for key in ("series_id", "series_title", "part_index", "planned_parts", "lesson_scope", "next_lesson_suggestions"):
                raw_value = record.get(key, "")
                if raw_value is None:
                    continue
                value = str(raw_value).strip()
                if value:
                    item[key] = value
            lessons.append(item)
            if len(lessons) >= limit:
                break
        return lessons

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.records, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def deduplicate_papers(papers: list[Paper]) -> list[Paper]:
    index_by_key: dict[str, int] = {}
    unique: list[Paper] = []
    for paper in papers:
        keys = _dedupe_keys(paper)
        duplicate_indexes = [index_by_key[key] for key in keys if key in index_by_key]
        if duplicate_indexes:
            index = min(duplicate_indexes)
            if _prefer_paper(paper, unique[index]):
                unique[index] = paper
                for key, existing_index in list(index_by_key.items()):
                    if existing_index == index:
                        del index_by_key[key]
                for key in keys:
                    index_by_key[key] = index
            continue
        index = len(unique)
        unique.append(paper)
        for key in keys:
            index_by_key[key] = index
    return unique


def _dedupe_keys(paper: Paper) -> set[str]:
    keys = {paper.paper_id, paper.url, _title_key(paper)}
    loose_title_key = _loose_title_key(paper)
    if loose_title_key:
        keys.add(loose_title_key)
    return keys


def _prefer_paper(candidate: Paper, existing: Paper) -> bool:
    candidate_rank = _source_preference_rank(candidate)
    existing_rank = _source_preference_rank(existing)
    if candidate_rank != existing_rank:
        return candidate_rank > existing_rank
    return _paper_timestamp(candidate) > _paper_timestamp(existing)


def _source_preference_rank(paper: Paper) -> int:
    if paper.is_prestige_journal_source:
        return 3
    if paper.source == "arXiv":
        return 2
    return 1


def _paper_timestamp(paper: Paper) -> str:
    timestamp = paper.updated or paper.published
    return timestamp.isoformat() if timestamp else ""


def _title_key(paper: Paper) -> str:
    return "title:" + _normalize_key_text(paper.title)


def _loose_title_key(paper: Paper) -> str | None:
    normalized = _normalize_loose_title(paper.title)
    if len(normalized) < 24:
        return None
    return "title_loose:" + normalized


def _lesson_title_key(title: str) -> str:
    return "lesson:title:" + _normalize_key_text(title)


def _lesson_anchor_key(anchor_work: str) -> str | None:
    normalized = _normalize_key_text(anchor_work)
    if not normalized:
        return None
    return "lesson:anchor:" + normalized


def _normalize_key_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _normalize_loose_title(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = text.replace("$", " ")
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = re.sub(r"[{}_^~]", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)
