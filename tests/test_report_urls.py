from pathlib import Path

from astro_daily.config import load_settings
from src.report_urls import latest_report_date, latest_report_url


def test_latest_report_url_uses_newest_existing_html(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  arxiv:
    primary:
      - category: astro-ph.HE
        max_results: 1
  rss:
    feeds: []
scoring: {}
llm: {}
report: {}
wechat:
  enabled: false
site_base_url: https://example.github.io/astro_daily
publish:
  docs_dir: docs
""".strip(),
        encoding="utf-8",
    )
    reports_dir = tmp_path / "docs" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "2026-05-02.html").write_text("", encoding="utf-8")
    (reports_dir / "2026-05-03.html").write_text("", encoding="utf-8")

    settings = load_settings(config_path)

    assert latest_report_date(settings).isoformat() == "2026-05-03"
    assert latest_report_url(settings) == "https://example.github.io/astro_daily/reports/2026-05-03.html"
