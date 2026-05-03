from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from email.utils import parsedate_to_datetime
from time import struct_time
from typing import Iterable

import feedparser
import requests
from requests import HTTPError

from astro_daily.config import ArxivCategoryConfig
from astro_daily.models import Paper

ARXIV_API_URL = "https://export.arxiv.org/api/query"


def fetch_arxiv_papers(
    categories: Iterable[ArxivCategoryConfig],
    *,
    days_back: int,
    timeout: int = 30,
) -> list[Paper]:
    papers: list[Paper] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    for item in categories:
        params = {
            "search_query": f"cat:{item.category}",
            "start": 0,
            "max_results": item.max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        response = _get_with_retry(params, timeout=timeout)
        feed = feedparser.parse(response.content)
        for entry in feed.entries:
            paper = _entry_to_paper(entry, item.category)
            if paper.published and paper.published < cutoff:
                continue
            papers.append(paper)
    return papers


def _get_with_retry(params: dict[str, object], *, timeout: int) -> requests.Response:
    last_error: HTTPError | None = None
    for attempt in range(3):
        if attempt:
            time.sleep(3 * attempt)
        response = requests.get(ARXIV_API_URL, params=params, timeout=timeout)
        try:
            response.raise_for_status()
            return response
        except HTTPError as exc:
            last_error = exc
            if response.status_code not in {429, 503}:
                raise
    raise last_error or RuntimeError("arXiv request failed")



def _entry_to_paper(entry: object, category: str) -> Paper:
    entry_id = _get(entry, "id") or _get(entry, "link")
    paper_id = _normalize_arxiv_id(entry_id)
    authors = [author.get("name", "").strip() for author in getattr(entry, "authors", [])]
    authors = [author for author in authors if author]
    tags = [tag.get("term", "") for tag in getattr(entry, "tags", [])]
    url = _get(entry, "link") or entry_id
    return Paper(
        paper_id=paper_id,
        title=_get(entry, "title"),
        authors=authors,
        abstract=_get(entry, "summary"),
        url=url,
        pdf_url=f"https://arxiv.org/pdf/{paper_id}",
        source="arXiv",
        category=category,
        published=_parse_entry_datetime(getattr(entry, "published_parsed", None), _get(entry, "published")),
        updated=_parse_entry_datetime(getattr(entry, "updated_parsed", None), _get(entry, "updated")),
        journal=None,
        tags=[tag for tag in tags if tag],
    )


def _normalize_arxiv_id(value: str) -> str:
    value = value.strip()
    for prefix in ("https://arxiv.org/abs/", "http://arxiv.org/abs/"):
        if value.startswith(prefix):
            value = value.removeprefix(prefix)
    return value.split("v")[0] if "/" not in value else value


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
