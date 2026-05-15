from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from pathlib import Path
import time
from time import struct_time

import feedparser
import requests
from requests import HTTPError

from astro_daily.config import RssFeedConfig
from astro_daily.models import Paper

REQUEST_HEADERS = {
    "User-Agent": "astro-daily/1.0 (+https://github.com/Yun532/astro_daily)",
    "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
}


def fetch_rss_papers(
    feeds: list[RssFeedConfig],
    *,
    max_entries_per_feed: int,
    timeout: int = 30,
    request_delay_seconds: float = 0,
    retry_attempts: int = 4,
    retry_initial_delay_seconds: float = 10,
    retry_max_delay_seconds: float = 300,
    cache_dir: str | Path | None = None,
    cache_ttl_seconds: float | None = None,
) -> list[Paper]:
    papers: list[Paper] = []
    for index, feed_config in enumerate(feeds):
        if index and request_delay_seconds > 0:
            time.sleep(request_delay_seconds)
        content = _get_cached_or_fetch_feed(
            feed_config.url,
            timeout=timeout,
            retry_attempts=retry_attempts,
            retry_initial_delay_seconds=retry_initial_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
            cache_dir=cache_dir,
            cache_ttl_seconds=cache_ttl_seconds,
        )
        feed = feedparser.parse(content)
        for entry in feed.entries[:max_entries_per_feed]:
            papers.append(_entry_to_paper(entry, feed_config))
    return papers


def _get_cached_or_fetch_feed(
    url: str,
    *,
    timeout: int,
    retry_attempts: int,
    retry_initial_delay_seconds: float,
    retry_max_delay_seconds: float,
    cache_dir: str | Path | None,
    cache_ttl_seconds: float | None,
) -> bytes:
    cache_path = _cache_path(cache_dir, url)
    if cache_path is not None and _cache_is_fresh(cache_path, cache_ttl_seconds):
        return cache_path.read_bytes()
    effective_retry_attempts = 1 if cache_path is not None and cache_path.exists() else retry_attempts
    try:
        response = _get_with_retry(
            url,
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
    raise last_error or RuntimeError("RSS request failed")


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


def _cache_path(cache_dir: str | Path | None, url: str) -> Path | None:
    if cache_dir is None:
        return None
    cache_key = url.encode("utf-8")
    return Path(cache_dir) / f"{hashlib.sha256(cache_key).hexdigest()}.xml"


def _cache_is_fresh(cache_path: Path, cache_ttl_seconds: float | None) -> bool:
    if not cache_path.exists():
        return False
    if cache_ttl_seconds is None or cache_ttl_seconds <= 0:
        return True
    return time.time() - cache_path.stat().st_mtime <= cache_ttl_seconds


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
