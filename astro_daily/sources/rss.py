from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import struct_time

import feedparser
import requests

from astro_daily.config import RssFeedConfig
from astro_daily.models import Paper


def fetch_rss_papers(
    feeds: list[RssFeedConfig],
    *,
    max_entries_per_feed: int,
    timeout: int = 30,
) -> list[Paper]:
    papers: list[Paper] = []
    for feed_config in feeds:
        response = requests.get(feed_config.url, timeout=timeout)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        for entry in feed.entries[:max_entries_per_feed]:
            papers.append(_entry_to_paper(entry, feed_config))
    return papers


def _entry_to_paper(entry: object, feed_config: RssFeedConfig) -> Paper:
    link = _get(entry, "link") or _get(entry, "id")
    doi = _get(entry, "prism_doi") or _get(entry, "dc_identifier")
    paper_id = doi or link or _get(entry, "title")
    authors = _parse_authors(entry)
    return Paper(
        paper_id=f"rss:{paper_id}",
        title=_get(entry, "title"),
        authors=authors,
        abstract=_get(entry, "summary") or _get(entry, "description"),
        url=link,
        pdf_url=None,
        source=feed_config.name,
        category=None,
        published=_parse_entry_datetime(getattr(entry, "published_parsed", None), _get(entry, "published")),
        updated=_parse_entry_datetime(getattr(entry, "updated_parsed", None), _get(entry, "updated")),
        journal=feed_config.name,
        tags=[tag.get("term", "") for tag in getattr(entry, "tags", []) if tag.get("term")],
    )


def _parse_authors(entry: object) -> list[str]:
    authors = [author.get("name", "").strip() for author in getattr(entry, "authors", [])]
    if authors:
        return [author for author in authors if author]
    author = _get(entry, "author")
    return [author] if author else []


def _parse_entry_datetime(parsed: struct_time | None, raw: str | None) -> datetime | None:
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    if raw:
        try:
            parsed_raw = parsedate_to_datetime(raw)
            if parsed_raw.tzinfo is None:
                return parsed_raw.replace(tzinfo=timezone.utc)
            return parsed_raw.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None
    return None


def _get(entry: object, key: str) -> str:
    value = getattr(entry, key, "")
    return " ".join(str(value).split())
