from datetime import date, datetime, timezone

import requests

from astro_daily.config import ArxivCategoryConfig, RssFeedConfig
from astro_daily.sources.arxiv import ArxivDailyListing, fetch_arxiv_papers, parse_arxiv_daily_listing
from astro_daily.sources.rss import fetch_rss_papers


class FakeResponse:
    def __init__(self, content: str, status_code: int = 200):
        self.content = content.encode("utf-8")
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            from requests import HTTPError

            raise HTTPError(response=self)
        return None


def test_arxiv_parser(monkeypatch):
    atom = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>https://arxiv.org/abs/2605.00001v1</id>
        <updated>2026-05-02T00:00:00Z</updated>
        <published>2026-05-02T00:00:00Z</published>
        <title> A high energy paper </title>
        <summary> Result summary. </summary>
        <author><name>Alice</name></author>
        <link href='https://arxiv.org/abs/2605.00001v1'/>
        <category term='astro-ph.HE'/>
      </entry>
    </feed>"""
    monkeypatch.setattr("astro_daily.sources.arxiv.requests.get", lambda *args, **kwargs: FakeResponse(atom))
    papers = fetch_arxiv_papers([ArxivCategoryConfig(category="astro-ph.HE", max_results=1)], days_back=30)
    assert papers[0].paper_id == "2605.00001"
    assert papers[0].category == "astro-ph.HE"
    assert papers[0].authors == ["Alice"]
    assert papers[0].published == datetime(2026, 5, 2, tzinfo=timezone.utc)
    assert papers[0].updated == datetime(2026, 5, 2, tzinfo=timezone.utc)



def test_arxiv_parser_applies_daily_listing_batch_date(monkeypatch):
    atom = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>https://arxiv.org/abs/2605.00001v1</id>
        <updated>2026-05-11T00:00:00Z</updated>
        <published>2026-05-11T00:00:00Z</published>
        <title> A daily batch paper </title>
        <summary> Result summary. </summary>
        <author><name>Alice</name></author>
      </entry>
    </feed>"""
    listing = ArxivDailyListing("astro-ph.HE", date(2026, 5, 12), {"2605.00001"}, True)
    monkeypatch.setattr("astro_daily.sources.arxiv.requests.get", lambda *args, **kwargs: FakeResponse(atom))

    papers = fetch_arxiv_papers(
        [ArxivCategoryConfig(category="astro-ph.HE", max_results=1)],
        days_back=30,
        daily_listings={"astro-ph.HE": listing},
    )

    assert papers[0].source_batch_date == date(2026, 5, 12)



def test_arxiv_retries_429(monkeypatch):
    calls = []
    atom = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>https://arxiv.org/abs/2605.00002v1</id>
        <published>2026-05-02T00:00:00Z</published>
        <title>Retry paper</title>
        <summary>Result summary.</summary>
        <author><name>Alice</name></author>
      </entry>
    </feed>"""

    def get(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse("", status_code=429)
        return FakeResponse(atom)

    monkeypatch.setattr("astro_daily.sources.arxiv.requests.get", get)
    monkeypatch.setattr("astro_daily.sources.arxiv.time.sleep", lambda seconds: None)

    papers = fetch_arxiv_papers([ArxivCategoryConfig(category="astro-ph.HE", max_results=1)], days_back=30)

    assert len(calls) == 2
    assert papers[0].paper_id == "2605.00002"



def test_arxiv_retries_timeout_with_configured_backoff(monkeypatch):
    calls = []
    sleeps = []
    atom = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>https://arxiv.org/abs/2605.00003v1</id>
        <published>2026-05-02T00:00:00Z</published>
        <title>Timeout retry paper</title>
        <summary>Result summary.</summary>
        <author><name>Alice</name></author>
      </entry>
    </feed>"""

    def get(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise requests.Timeout("slow arXiv")
        return FakeResponse(atom)

    monkeypatch.setattr("astro_daily.sources.arxiv.requests.get", get)
    monkeypatch.setattr("astro_daily.sources.arxiv.time.sleep", sleeps.append)

    papers = fetch_arxiv_papers(
        [ArxivCategoryConfig(category="astro-ph.HE", max_results=1)],
        days_back=30,
        retry_initial_delay_seconds=7,
    )

    assert sleeps == [7]
    assert papers[0].paper_id == "2605.00003"



def test_arxiv_uses_cached_api_response(monkeypatch, tmp_path):
    calls = []
    atom = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>https://arxiv.org/abs/2605.00004v1</id>
        <published>2026-05-02T00:00:00Z</published>
        <title>Cached paper</title>
        <summary>Result summary.</summary>
        <author><name>Alice</name></author>
      </entry>
    </feed>"""

    def get(*args, **kwargs):
        calls.append(1)
        return FakeResponse(atom)

    monkeypatch.setattr("astro_daily.sources.arxiv.requests.get", get)
    config = [ArxivCategoryConfig(category="astro-ph.HE", max_results=1)]

    first = fetch_arxiv_papers(config, days_back=30, cache_dir=tmp_path, cache_ttl_seconds=3600)
    second = fetch_arxiv_papers(config, days_back=30, cache_dir=tmp_path, cache_ttl_seconds=3600)

    assert len(calls) == 1
    assert first[0].paper_id == "2605.00004"
    assert second[0].paper_id == "2605.00004"



def test_arxiv_daily_listing_parser_extracts_date_and_ids():
    html = """
    <html><body>
      <h3>New submissions for Tue, 12 May 2026</h3>
      <a href="/abs/2605.10411v1">arXiv:2605.10411</a>
      <a href="/abs/2605.10559">arXiv:2605.10559</a>
    </body></html>
    """

    listing = parse_arxiv_daily_listing("astro-ph.HE", html)

    assert listing.available
    assert listing.listing_date.isoformat() == "2026-05-12"
    assert listing.paper_ids == {"2605.10411", "2605.10559"}



def test_arxiv_daily_listing_parser_excludes_replacements():
    html = """
    <html><body>
      <h3>Showing new listings for Tuesday, 12 May 2026</h3>
      <h3>New submissions (showing 1 of 1 entries)</h3>
      <a href="/abs/2605.10001">arXiv:2605.10001</a>
      <h3>Cross submissions (showing 1 of 1 entries)</h3>
      <a href="/abs/2605.08010">arXiv:2605.08010</a>
      <h3>Replacement submissions (showing 1 of 1 entries)</h3>
      <a href="/abs/2605.07001">arXiv:2605.07001</a>
    </body></html>
    """

    listing = parse_arxiv_daily_listing("astro-ph.HE", html)

    assert listing.paper_ids == {"2605.10001", "2605.08010"}



def test_rss_parser(monkeypatch):
    rss = """<?xml version='1.0' encoding='UTF-8'?>
    <rss version='2.0'><channel><title>Nature Astronomy</title>
      <item>
        <title>Cosmic-ray detection</title>
        <link>https://example.com/paper</link>
        <description>Short summary.</description>
        <pubDate>Sat, 02 May 2026 00:00:00 +0000</pubDate>
        <author>Alice</author>
      </item>
    </channel></rss>"""
    monkeypatch.setattr("astro_daily.sources.rss.requests.get", lambda *args, **kwargs: FakeResponse(rss))
    papers = fetch_rss_papers([RssFeedConfig(name="Nature", url="https://example.com/rss")], max_entries_per_feed=10)
    assert papers[0].source == "Nature"
    assert papers[0].title == "Cosmic-ray detection"
    assert papers[0].published == datetime(2026, 5, 2, tzinfo=timezone.utc)
