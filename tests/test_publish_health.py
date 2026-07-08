from datetime import date
from pathlib import Path

import pytest

from astro_daily.config import (
    ArxivCategoryConfig,
    ArxivConfig,
    ClawBotConfig,
    LlmConfig,
    PublishConfig,
    ReportConfig,
    RssConfig,
    ScoringConfig,
    Settings,
    SourcesConfig,
    WechatConfig,
)
from astro_daily.publish_health import PublishHealthError, ensure_publish_health, validate_publish_health


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        sources=SourcesConfig(
            arxiv=ArxivConfig(primary=[ArxivCategoryConfig(category="astro-ph.HE")]),
            rss=RssConfig(),
        ),
        scoring=ScoringConfig(),
        llm=LlmConfig(),
        report=ReportConfig(output_dir="reports", seen_file="seen.json"),
        wechat=WechatConfig(enabled=True),
        clawbot=ClawBotConfig(enabled=False),
        publish=PublishConfig(enabled=True, docs_dir="docs"),
        anthropic_api_key="test-token",
        root_dir=tmp_path,
        site_base_url="https://example.com/astro_daily",
    )


def write_html(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "docs" / "reports" / "2026-07-08.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return path


def test_publish_health_accepts_valid_report_and_wechat_message(tmp_path: Path):
    settings = make_settings(tmp_path)
    asset = tmp_path / "docs" / "assets" / "figures" / "plot.png"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"fake png")
    html = write_html(tmp_path, '<p>公式 \\(E=mc^2\\) 正常。</p><img src="../assets/figures/plot.png">')
    url = "https://example.com/astro_daily/reports/2026-07-08.html"

    result = ensure_publish_health(
        settings=settings,
        html_report_path=html,
        wechat_message=f"# 天文日报｜2026-07-08\n\n[完整报告]({url})",
        report_url=url,
    )

    assert result.ok
    assert result.error_count == 0


def test_publish_health_rejects_missing_local_images(tmp_path: Path):
    settings = make_settings(tmp_path)
    html = write_html(tmp_path, '<p>正文。</p><img src="../assets/figures/missing.png">')

    result = validate_publish_health(
        settings=settings,
        html_report_path=html,
        wechat_message="# 天文日报｜2026-07-08\n\n[完整报告](https://example.com/astro_daily/reports/2026-07-08.html)",
        report_url="https://example.com/astro_daily/reports/2026-07-08.html",
    )

    assert not result.ok
    assert any(issue.kind == "missing_local_image" for issue in result.issues)


def test_publish_health_rejects_wechat_question_mark_mojibake(tmp_path: Path):
    settings = make_settings(tmp_path)
    html = write_html(tmp_path, "<p>正文。</p>")
    url = "https://example.com/astro_daily/reports/2026-07-08.html"

    with pytest.raises(PublishHealthError):
        ensure_publish_health(
            settings=settings,
            html_report_path=html,
            wechat_message=f"Astro Daily ????\n??????????\n{url}",
            report_url=url,
        )


def test_publish_health_rejects_too_long_wechat_message(tmp_path: Path):
    settings = make_settings(tmp_path)
    html = write_html(tmp_path, "<p>正文。</p>")
    url = "https://example.com/astro_daily/reports/2026-07-08.html"
    message = "# 天文日报｜2026-07-08\n" + ("很长" * 3000) + f"\n[完整报告]({url})"

    result = validate_publish_health(
        settings=settings,
        html_report_path=html,
        wechat_message=message,
        report_url=url,
    )

    assert not result.ok
    assert any(issue.kind == "wechat_too_long" for issue in result.issues)


def test_publish_health_rejects_missing_wechat_report_url(tmp_path: Path):
    settings = make_settings(tmp_path)
    html = write_html(tmp_path, "<p>正文。</p>")

    result = validate_publish_health(
        settings=settings,
        html_report_path=html,
        wechat_message="# 天文日报｜2026-07-08",
        report_url="https://example.com/astro_daily/reports/2026-07-08.html",
    )

    assert not result.ok
    assert any(issue.kind == "wechat_missing_report_url" for issue in result.issues)
