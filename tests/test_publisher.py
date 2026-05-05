from datetime import date
from pathlib import Path

import pytest

from astro_daily.config import load_settings
from src.publisher import publish_report_if_enabled


def write_config(tmp_path: Path, publish_block: str) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
sources:
  arxiv:
    primary:
      - category: astro-ph.HE
        max_results: 1
  rss:
    feeds: []
scoring: {{}}
llm: {{}}
report: {{}}
wechat:
  enabled: false
site_base_url: https://example.github.io/astro-daily
{publish_block}
""".strip(),
        encoding="utf-8",
    )
    return config_path


def write_html(tmp_path: Path) -> Path:
    html_path = tmp_path / "docs" / "reports" / "2026-05-02.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<html></html>", encoding="utf-8")
    return html_path


def test_disabled_publisher_is_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    settings = load_settings(write_config(tmp_path, "publish: {}"))
    result = publish_report_if_enabled(settings, str(write_html(tmp_path)), date(2026, 5, 2))
    assert not result.enabled
    assert not result.published
    assert result.url == "https://example.github.io/astro-daily/reports/2026-05-02.html"


def test_dry_run_does_not_call_git(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    settings = load_settings(write_config(tmp_path, "publish:\n  enabled: true"))
    result = publish_report_if_enabled(settings, str(write_html(tmp_path)), date(2026, 5, 2), dry_run=True)
    output = capsys.readouterr().out
    assert result.enabled
    assert not result.published
    assert "Dry-run publish: git add docs/reports/2026-05-02.html" in output
    assert result.url == "https://example.github.io/astro-daily/reports/2026-05-02.html"


def test_refuses_to_publish_outside_docs_reports(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    settings = load_settings(write_config(tmp_path, "publish:\n  enabled: true"))
    unexpected = tmp_path / "daily_reports" / "2026-05-02.html"
    unexpected.parent.mkdir()
    unexpected.write_text("<html></html>", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unexpected path"):
        publish_report_if_enabled(settings, str(unexpected), date(2026, 5, 2), dry_run=True)


def test_enabled_publisher_runs_git_for_single_report_and_assets(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    settings = load_settings(write_config(tmp_path, "publish:\n  enabled: true"))
    asset_dir = tmp_path / "docs" / "assets" / "figures" / "2026-05-02" / "2605.00001"
    asset_dir.mkdir(parents=True)
    (asset_dir / "Fig01.png").write_bytes(b"png")
    calls = []

    def fake_run_git(root, args, *, capture_output=True, check=True):
        calls.append(args)
        class Result:
            returncode = 0
            stdout = "origin\n" if args == ["remote"] else ""
            stderr = ""
        if args[:3] == ["diff", "--cached", "--quiet"]:
            Result.returncode = 1
        return Result()

    monkeypatch.setattr("src.publisher._run_git", fake_run_git)
    result = publish_report_if_enabled(settings, str(write_html(tmp_path)), date(2026, 5, 2))

    assert result.published
    assert ["add", "--", "docs/reports/2026-05-02.html", "docs/assets/figures/2026-05-02"] in calls
    assert ["commit", "-m", "Publish Astro Daily report 2026-05-02"] in calls
    assert ["push", "origin", "main"] in calls


def test_no_staged_changes_counts_as_published(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    settings = load_settings(write_config(tmp_path, "publish:\n  enabled: true"))
    calls = []

    def fake_run_git(root, args, *, capture_output=True, check=True):
        calls.append(args)
        class Result:
            returncode = 0
            stdout = "origin\n" if args == ["remote"] else ""
            stderr = ""
        return Result()

    monkeypatch.setattr("src.publisher._run_git", fake_run_git)
    result = publish_report_if_enabled(settings, str(write_html(tmp_path)), date(2026, 5, 2))

    assert result.published
    assert not any(call and call[0] == "commit" for call in calls)
    assert not any(call and call[0] == "push" for call in calls)
