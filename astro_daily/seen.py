from __future__ import annotations

import json
import logging
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
        return paper.paper_id in self.records or _title_key(paper) in self.records

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

    def mark_lessons(self, lessons: list[WeekendLesson], *, seen_date: date) -> None:
        for lesson in lessons:
            record = {
                "type": "weekend_lesson",
                "topic": lesson.topic,
                "title": lesson.title_cn,
                "anchor_work": lesson.anchor_work_cn,
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
            lessons.append(
                {
                    "title": title,
                    "topic": str(record.get("topic", "")).strip(),
                    "anchor_work": str(record.get("anchor_work", "")).strip(),
                }
            )
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
    seen: set[str] = set()
    unique: list[Paper] = []
    for paper in papers:
        keys = {paper.paper_id, paper.url, _title_key(paper)}
        if seen.intersection(keys):
            continue
        seen.update(keys)
        unique.append(paper)
    return unique


def _title_key(paper: Paper) -> str:
    return "title:" + _normalize_key_text(paper.title)


def _lesson_title_key(title: str) -> str:
    return "lesson:title:" + _normalize_key_text(title)


def _lesson_anchor_key(anchor_work: str) -> str | None:
    normalized = _normalize_key_text(anchor_work)
    if not normalized:
        return None
    return "lesson:anchor:" + normalized


def _normalize_key_text(text: str) -> str:
    return " ".join(text.casefold().split())
