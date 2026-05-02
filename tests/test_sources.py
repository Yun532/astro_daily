from astro_daily.config import ArxivCategoryConfig, RssFeedConfig
from astro_daily.sources.arxiv import fetch_arxiv_papers
from astro_daily.sources.rss import fetch_rss_papers


class FakeResponse:
    def __init__(self, content: str):
        self.content = content.encode("utf-8")

    def raise_for_status(self):
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
