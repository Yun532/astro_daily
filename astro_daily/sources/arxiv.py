from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
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
ARXIV_LIST_URL = "https://arxiv.org/list/{category}/new"
ARXIV_LISTING_DATE_RE = re.compile(r"(?:New submissions for|Showing new listings for)\s+([^<]+)", re.IGNORECASE)
ARXIV_LISTING_DAY_RE = re.compile(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
ARXIV_ABS_ID_RE = re.compile(r"/abs/([\w.\-/]+)")
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass(frozen=True)
class ArxivDailyListing:
    category: str
    listing_date: date | None
    paper_ids: set[str]
    available: bool


def fetch_arxiv_daily_listing(category: str, *, timeout: int = 30) -> ArxivDailyListing:
    response = requests.get(ARXIV_LIST_URL.format(category=category), timeout=timeout)
    response.raise_for_status()
    return parse_arxiv_daily_listing(category, response.text)


def parse_arxiv_daily_listing(category: str, html: str) -> ArxivDailyListing:
    date_match = ARXIV_LISTING_DATE_RE.search(html)
    listing_date = _parse_listing_date(date_match.group(1)) if date_match else None
    paper_ids = {_normalize_arxiv_id(match.group(1)) for match in ARXIV_ABS_ID_RE.finditer(html)}
    return ArxivDailyListing(
        category=category,
        listing_date=listing_date,
        paper_ids=paper_ids,
        available=listing_date is not None and bool(paper_ids),
    )


def annotate_arxiv_batch(papers: list[Paper], listing: ArxivDailyListing) -> list[Paper]:
    if not listing.available or listing.listing_date is None:
        return papers
    for paper in papers:
        if paper.source == "arXiv" and paper.category == listing.category and paper.paper_id in listing.paper_ids:
            paper.source_batch_date = listing.listing_date
    return papers


def fetch_arxiv_papers(
    categories: Iterable[ArxivCategoryConfig],
    *,
    days_back: int,
    timeout: int = 30,
    daily_listings: dict[str, ArxivDailyListing] | None = None,
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
            listing = (daily_listings or {}).get(item.category)
            if listing and listing.available and listing.listing_date is not None and paper.paper_id in listing.paper_ids:
                paper.source_batch_date = listing.listing_date
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


def _parse_listing_date(raw: str) -> date | None:
    text = raw.strip()
    day_match = ARXIV_LISTING_DAY_RE.search(text)
    if day_match:
        day, month_name, year = day_match.groups()
        month = MONTHS.get(month_name.casefold())
        if month is not None:
            return date(int(year), month, int(day))
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError):
        return None


def _get(entry: object, key: str) -> str:
    value = getattr(entry, key, "")
    return " ".join(str(value).split())
