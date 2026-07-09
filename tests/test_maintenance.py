from datetime import date, datetime
from pathlib import Path
import os

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
from astro_daily.maintenance import cleanup_runtime_artifacts


def make_settings(tmp_path: Path) -> Settings:
    settings = Settings(
        sources=SourcesConfig(
            arxiv=ArxivConfig(primary=[ArxivCategoryConfig(category="astro-ph.HE")]),
            rss=RssConfig(),
        ),
        scoring=ScoringConfig(),
        llm=LlmConfig(),
        report=ReportConfig(output_dir="reports", seen_file="seen.json"),
        wechat=WechatConfig(enabled=False),
        clawbot=ClawBotConfig(enabled=False),
        publish=PublishConfig(enabled=False),
        anthropic_api_key="test-token",
        root_dir=tmp_path,
    )
    settings.maintenance.figure_asset_keep_recent_dates = 2
    settings.maintenance.figure_cache_retention_days = 14
    return settings


def write_file(path: Path, data: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def set_mtime(path: Path, when: datetime) -> None:
    timestamp = when.timestamp()
    os.utime(path, (timestamp, timestamp))


def test_cleanup_runtime_artifacts_dry_run_does_not_delete(tmp_path: Path):
    settings = make_settings(tmp_path)
    old_asset = tmp_path / "docs" / "assets" / "figures" / "2026-05-01" / "paper" / "Fig01.png"
    write_file(old_asset)
    write_file(tmp_path / "docs" / "assets" / "figures" / "2026-07-08" / "paper" / "Fig01.png")
    write_file(tmp_path / "docs" / "assets" / "figures" / "2026-07-09" / "paper" / "Fig01.png")

    result = cleanup_runtime_artifacts(settings, run_date=date(2026, 7, 9), dry_run=True)

    assert result.asset_removed_count == 1
    assert old_asset.exists()


def test_cleanup_runtime_artifacts_removes_old_cache_and_assets(tmp_path: Path):
    settings = make_settings(tmp_path)
    old_cache = tmp_path / "figure_cache" / "2605.00001"
    new_cache = tmp_path / "figure_cache" / "2607.00001"
    write_file(old_cache / "paper.pdf", b"old")
    write_file(new_cache / "paper.pdf", b"new")
    set_mtime(old_cache, datetime(2026, 6, 1))
    set_mtime(new_cache, datetime(2026, 7, 8))

    for day in ["2026-07-01", "2026-07-08", "2026-07-09"]:
        write_file(tmp_path / "docs" / "assets" / "figures" / day / "paper" / "Fig01.png", day.encode())

    result = cleanup_runtime_artifacts(settings, run_date=date(2026, 7, 9), dry_run=False)

    assert result.cache_removed_count == 1
    assert result.asset_removed_count == 1
    assert not old_cache.exists()
    assert new_cache.exists()
    assert not (tmp_path / "docs" / "assets" / "figures" / "2026-07-01").exists()
    assert (tmp_path / "docs" / "assets" / "figures" / "2026-07-08").exists()
    assert (tmp_path / "docs" / "assets" / "figures" / "2026-07-09").exists()
    assert result.kept_asset_dates == ["2026-07-08", "2026-07-09"]
