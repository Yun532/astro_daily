from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
from pathlib import Path
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
REQUEST_HEADERS = {
    "User-Agent": "astro-daily/1.0 (+https://github.com/Yun532/astro_daily)",
    "Accept": "application/atom+xml,text/html,application/xml;q=0.9,*/*;q=0.8",
}
ARXIV_LISTING_DATE_RE = re.compile(r"(?:New submissions for|Showing new listings for)\s+([^<]+)", re.IGNORECASE)
ARXIV_LISTING_DAY_RE = re.compile(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
ARXIV_ABS_ID_RE = re.compile(r"/abs/([\w.\-/]+)")
ARXIV_SECTION_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]+>")
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


def fetch_arxiv_daily_listing(
    category: str,
    *,
    timeout: int = 30,
    retry_attempts: int = 3,
    retry_initial_delay_seconds: float = 3,
    retry_max_delay_seconds: float = 60,
    cache_dir: str | Path | None = None,
    cache_ttl_seconds: float | None = None,
) -> ArxivDailyListing:
    url = ARXIV_LIST_URL.format(category=category)
    cache_path = _listing_cache_path(cache_dir, category)
    if cache_path is not None and _cache_is_fresh(cache_path, cache_ttl_seconds):
        return parse_arxiv_daily_listing(category, cache_path.read_text(encoding="utf-8"))
    effective_retry_attempts = 1 if cache_path is not None and cache_path.exists() else retry_attempts
    try:
        response = _get_url_with_retry(
            url,
            timeout=timeout,
            retry_attempts=effective_retry_attempts,
            retry_initial_delay_seconds=retry_initial_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
        )
    except Exception as exc:
        if cache_path is not None and cache_path.exists() and _can_use_stale_cache(exc):
            return parse_arxiv_daily_listing(category, cache_path.read_text(encoding="utf-8"))
        raise
    text = response.content.decode(getattr(response, "encoding", None) or "utf-8", errors="replace")
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
    return parse_arxiv_daily_listing(category, text)


def parse_arxiv_daily_listing(category: str, html: str) -> ArxivDailyListing:
    date_match = ARXIV_LISTING_DATE_RE.search(html)
    listing_date = _parse_listing_date(date_match.group(1)) if date_match else None
    paper_ids = _extract_daily_listing_ids(html)
    return ArxivDailyListing(
        category=category,
        listing_date=listing_date,
        paper_ids=paper_ids,
        available=listing_date is not None and bool(paper_ids),
    )


def _extract_daily_listing_ids(html: str) -> set[str]:
    sections = list(ARXIV_SECTION_RE.finditer(html))
    if not sections:
        return {_normalize_arxiv_id(match.group(1)) for match in ARXIV_ABS_ID_RE.finditer(html)}
    paper_ids: set[str] = set()
    matched_daily_section = False
    for index, section in enumerate(sections):
        title = HTML_TAG_RE.sub("", section.group(1)).strip().casefold()
        if "replacement submissions" in title:
            continue
        if "new submissions" not in title and "cross submissions" not in title:
            continue
        matched_daily_section = True
        end = sections[index + 1].start() if index + 1 < len(sections) else len(html)
        segment = html[section.end() : end]
        paper_ids.update(_normalize_arxiv_id(match.group(1)) for match in ARXIV_ABS_ID_RE.finditer(segment))
    if matched_daily_section:
        return paper_ids
    return {_normalize_arxiv_id(match.group(1)) for match in ARXIV_ABS_ID_RE.finditer(html)}



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
    request_delay_seconds: float = 0,
    retry_attempts: int = 3,
    retry_initial_delay_seconds: float = 3,
    retry_max_delay_seconds: float = 60,
    cache_dir: str | Path | None = None,
    cache_ttl_seconds: float | None = None,
) -> list[Paper]:
    papers: list[Paper] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    for index, item in enumerate(categories):
        if index and request_delay_seconds > 0:
            time.sleep(request_delay_seconds)
        params = {
            "search_query": f"cat:{item.category}",
            "start": 0,
            "max_results": item.max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        listing = (daily_listings or {}).get(item.category)
        content = _get_cached_or_fetch(
            params,
            timeout=timeout,
            retry_attempts=retry_attempts,
            retry_initial_delay_seconds=retry_initial_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
            cache_dir=cache_dir,
            cache_ttl_seconds=cache_ttl_seconds,
            cache_context=_listing_cache_context(listing),
        )
        feed = feedparser.parse(content)
        for entry in feed.entries:
            paper = _entry_to_paper(entry, item.category)
            if listing and listing.available and listing.listing_date is not None and paper.paper_id in listing.paper_ids:
                paper.source_batch_date = listing.listing_date
            if paper.published and paper.published < cutoff:
                continue
            papers.append(paper)
    return papers


def fetch_arxiv_papers_by_ids(
    category: str,
    paper_ids: Iterable[str],
    *,
    source_batch_date: date | None = None,
    timeout: int = 30,
    request_delay_seconds: float = 0,
    retry_attempts: int = 3,
    retry_initial_delay_seconds: float = 3,
    retry_max_delay_seconds: float = 60,
    cache_dir: str | Path | None = None,
    cache_ttl_seconds: float | None = None,
    chunk_size: int = 100,
) -> list[Paper]:
    papers: list[Paper] = []
    normalized_ids = sorted({_normalize_arxiv_id(paper_id) for paper_id in paper_ids if paper_id})
    if not normalized_ids:
        return papers
    for index, chunk in enumerate(_chunks(normalized_ids, chunk_size)):
        if index and request_delay_seconds > 0:
            time.sleep(request_delay_seconds)
        params = {
            "id_list": ",".join(chunk),
            "start": 0,
            "max_results": len(chunk),
        }
        content = _get_cached_or_fetch(
            params,
            timeout=timeout,
            retry_attempts=retry_attempts,
            retry_initial_delay_seconds=retry_initial_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
            cache_dir=cache_dir,
            cache_ttl_seconds=cache_ttl_seconds,
            cache_context=f"id-list:{category}:{source_batch_date}",
        )
        feed = feedparser.parse(content)
        for entry in feed.entries:
            paper = _entry_to_paper(entry, category)
            if source_batch_date is not None and paper.paper_id in normalized_ids:
                paper.source_batch_date = source_batch_date
            papers.append(paper)
    return papers


def _chunks(items: list[str], chunk_size: int) -> Iterable[list[str]]:
    chunk_size = max(1, chunk_size)
    for index in range(0, len(items), chunk_size):
        yield items[index : index + chunk_size]


def _get_cached_or_fetch(
    params: dict[str, object],
    *,
    timeout: int,
    retry_attempts: int,
    retry_initial_delay_seconds: float,
    retry_max_delay_seconds: float,
    cache_dir: str | Path | None,
    cache_ttl_seconds: float | None,
    cache_context: str,
) -> bytes:
    cache_path = _cache_path(cache_dir, params, cache_context)
    if cache_path is not None and _cache_is_fresh(cache_path, cache_ttl_seconds):
        return cache_path.read_bytes()
    effective_retry_attempts = 1 if cache_path is not None and cache_path.exists() else retry_attempts
    try:
        response = _get_with_retry(
            params,
            timeout=timeout,
            retry_attempts=effective_retry_attempts,
            retry_initial_delay_seconds=retry_initial_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
        )
    except Exception as exc:
        if cache_path is not None and cache_path.exists() and _can_use_stale_cache(exc):
            return cache_path.read_bytes()
        raise
    content = response.content
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)
    return content


def _get_with_retry(
    params: dict[str, object],
    *,
    timeout: int,
    retry_attempts: int,
    retry_initial_delay_seconds: float,
    retry_max_delay_seconds: float,
) -> requests.Response:
    last_error: Exception | None = None
    delay = retry_initial_delay_seconds
    for attempt in range(retry_attempts):
        if attempt and delay > 0:
            time.sleep(delay)
            delay = _next_retry_delay(delay, retry_max_delay_seconds)
        try:
            response = requests.get(ARXIV_API_URL, params=params, timeout=timeout, headers=REQUEST_HEADERS)
            response.raise_for_status()
            return response
        except HTTPError as exc:
            last_error = exc
            status_code = getattr(exc.response, "status_code", None) or getattr(locals().get("response", None), "status_code", None)
            if status_code not in {429, 503}:
                raise
            retry_after_delay = _retry_after_delay(getattr(exc.response, "headers", None), retry_max_delay_seconds)
            if retry_after_delay is not None:
                delay = retry_after_delay
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
    raise last_error or RuntimeError("arXiv request failed")


def _get_url_with_retry(
    url: str,
    *,
    timeout: int,
    retry_attempts: int,
    retry_initial_delay_seconds: float,
    retry_max_delay_seconds: float,
) -> requests.Response:
    last_error: Exception | None = None
    delay = retry_initial_delay_seconds
    for attempt in range(retry_attempts):
        if attempt and delay > 0:
            time.sleep(delay)
            delay = _next_retry_delay(delay, retry_max_delay_seconds)
        try:
            response = requests.get(url, timeout=timeout, headers=REQUEST_HEADERS)
            response.raise_for_status()
            return response
        except HTTPError as exc:
            last_error = exc
            status_code = getattr(exc.response, "status_code", None) or getattr(locals().get("response", None), "status_code", None)
            if status_code not in {429, 503}:
                raise
            retry_after_delay = _retry_after_delay(getattr(exc.response, "headers", None), retry_max_delay_seconds)
            if retry_after_delay is not None:
                delay = retry_after_delay
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
    raise last_error or RuntimeError("arXiv request failed")



def _next_retry_delay(current_delay: float, max_delay: float) -> float:
    if current_delay <= 0:
        return 0
    return min(current_delay * 2, max_delay)


def _retry_after_delay(headers: object | None, max_delay: float) -> float | None:
    retry_after = getattr(headers, "get", lambda _key: None)("Retry-After") if headers is not None else None
    if retry_after is None:
        return None
    try:
        return min(float(retry_after), max_delay)
    except ValueError:
        return None


def _can_use_stale_cache(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, HTTPError):
        status_code = getattr(exc.response, "status_code", None)
        return status_code in {429, 503}
    return False


def _cache_path(cache_dir: str | Path | None, params: dict[str, object], cache_context: str) -> Path | None:
    if cache_dir is None:
        return None
    cache_key = repr((sorted(params.items()), cache_context)).encode("utf-8")
    return Path(cache_dir) / f"{hashlib.sha256(cache_key).hexdigest()}.xml"


def _listing_cache_path(cache_dir: str | Path | None, category: str) -> Path | None:
    if cache_dir is None:
        return None
    cache_key = f"daily-listing:{category}".encode("utf-8")
    return Path(cache_dir) / f"{hashlib.sha256(cache_key).hexdigest()}.html"


def _cache_is_fresh(cache_path: Path, cache_ttl_seconds: float | None) -> bool:
    if not cache_path.exists():
        return False
    if cache_ttl_seconds is None or cache_ttl_seconds <= 0:
        return True
    return time.time() - cache_path.stat().st_mtime <= cache_ttl_seconds


def _listing_cache_context(listing: ArxivDailyListing | None) -> str:
    if listing is None:
        return "no-listing"
    ids_digest = hashlib.sha256("\n".join(sorted(listing.paper_ids)).encode("utf-8")).hexdigest()
    return f"{listing.category}:{listing.listing_date}:{listing.available}:{ids_digest}"


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
