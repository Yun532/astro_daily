from astro_daily.config import ArxivCategoryConfig, RssFeedConfig
from astro_daily.sources.arxiv import fetch_arxiv_papers
from astro_daily.sources.rss import fetch_rss_papers


class FakeResponse:
    def __init__(self, content: str, status_code: int = 200):
        self.content = content.encode("utf-8")
        self.status_code = status_code

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
    papers = fetch_arxiv_papers([ArxivCategoryConfig(category="astro-ph.HE", max_results=1)], days_back=10)
    assert papers[0].paper_id == "2605.00001"
    assert papers[0].category == "astro-ph.HE"
    assert papers[0].authors == ["Alice"]


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

    papers = fetch_arxiv_papers([ArxivCategoryConfig(category="astro-ph.HE", max_results=1)], days_back=10)

    assert len(calls) == 2
    assert papers[0].paper_id == "2605.00002"



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
