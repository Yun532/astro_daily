from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from astro_daily.models import Paper, PaperScore, ScoredPaper
from astro_daily.seen import SeenStore

logger = logging.getLogger(__name__)


class ClassicPaperEntry(BaseModel):
    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    url: str
    topic: str
    tags: list[str] = Field(default_factory=list)
    why_classic_cn: str

    @field_validator("id", "title", "url", "topic", "why_classic_cn")
    @classmethod
    def not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("classic paper fields must not be empty")
        return value


def load_classic_papers(path: Path) -> list[ClassicPaperEntry]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):
        raw = raw.get("papers", [])
    if not isinstance(raw, list):
        raise ValueError(f"classic paper catalog must be a list or contain a papers list: {path}")
    entries: list[ClassicPaperEntry] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            logger.warning("Ignoring malformed classic paper catalog entry %s in %s", index, path)
            continue
        try:
            entries.append(ClassicPaperEntry.model_validate(item))
        except ValueError as exc:
            logger.warning("Ignoring invalid classic paper catalog entry %s in %s: %s", index, path, exc)
    return entries


def select_classic_paper(path: Path, seen: SeenStore) -> ScoredPaper | None:
    try:
        entries = load_classic_papers(path)
    except ValueError as exc:
        logger.warning("Classic paper catalog could not be loaded: %s", exc)
        return None
    for entry in entries:
        paper = classic_entry_to_paper(entry)
        if not seen.is_seen(paper):
            return ScoredPaper(
                paper=paper,
                score=PaperScore(
                    novelty_score=6,
                    importance_score=10,
                    relevance_to_me=9,
                    final_score=9.0,
                    keep=True,
                    reason=f"经典旧文精读：{entry.why_classic_cn}",
                ),
            )
    return None


def classic_entry_to_paper(entry: ClassicPaperEntry) -> Paper:
    published = datetime(entry.year, 1, 1, tzinfo=timezone.utc) if entry.year else None
    return Paper(
        paper_id=f"classic:{entry.id}",
        title=entry.title,
        authors=entry.authors,
        abstract=entry.why_classic_cn,
        url=entry.url,
        pdf_url=None,
        source="Classic Paper",
        category="classic",
        published=published,
        updated=None,
        source_batch_date=None,
        journal=entry.topic,
        tags=[entry.topic, *entry.tags],
    )
