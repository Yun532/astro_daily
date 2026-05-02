from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from astro_daily.models import Paper

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
                "title": paper.title,
                "url": paper.url,
                "source": paper.source,
                "category": paper.category,
                "first_seen": seen_date.isoformat(),
            }
            self.records[_title_key(paper)] = {
                "paper_id": paper.paper_id,
                "first_seen": seen_date.isoformat(),
            }

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
    return "title:" + " ".join(paper.title.casefold().split())
