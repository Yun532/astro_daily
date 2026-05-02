from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from astro_daily.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    enabled: bool
    published: bool
    url: str | None


def publish_report_if_enabled(settings: Settings, html_report_path: str, run_date: date, *, dry_run: bool = False) -> PublishResult:
    url = _report_url(settings.site_base_url, run_date)
    if not settings.publish.enabled:
        return PublishResult(enabled=False, published=False, url=url)
    if settings.publish.provider != "github_pages" or settings.publish.mode != "git_push":
        raise RuntimeError("Only GitHub Pages git_push publishing is supported")

    path = Path(html_report_path).resolve()
    root = settings.root_dir.resolve()
    relative_path = path.relative_to(root)
    expected_prefix = Path(settings.publish.docs_dir) / "reports"
    if not _is_relative_to(relative_path, expected_prefix):
        raise RuntimeError(f"Refusing to publish unexpected path: {relative_path}")

    if dry_run:
        print(f"Dry-run publish: git add {relative_path.as_posix()}")
        print(f"Dry-run publish: git commit -m \"{_commit_message(settings, run_date)}\"")
        print(f"Dry-run publish: git push origin {settings.publish.branch}")
        return PublishResult(enabled=True, published=False, url=url)

    _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    _ensure_remote(root, settings.publish.repo_url)
    _run_git(root, ["add", "--", relative_path.as_posix()])
    if not _has_staged_changes(root, relative_path):
        logger.info("No report changes to publish for %s", relative_path.as_posix())
        return PublishResult(enabled=True, published=True, url=url)
    _run_git(root, ["commit", "-m", _commit_message(settings, run_date)])
    _run_git(root, ["push", "origin", settings.publish.branch])
    return PublishResult(enabled=True, published=True, url=url)


def _report_url(site_base_url: str, run_date: date) -> str:
    return f"{site_base_url.rstrip('/')}/reports/{run_date.isoformat()}.html"


def _commit_message(settings: Settings, run_date: date) -> str:
    return settings.publish.commit_message_template.format(date=run_date.isoformat())


def _ensure_remote(root: Path, repo_url: str | None) -> None:
    existing = _run_git(root, ["remote"], capture_output=True).stdout.split()
    if "origin" in existing:
        return
    if not repo_url:
        raise RuntimeError("Git remote origin is not configured; set publish.repo_url or add origin manually")
    _run_git(root, ["remote", "add", "origin", repo_url])


def _has_staged_changes(root: Path, relative_path: Path) -> bool:
    result = _run_git(root, ["diff", "--cached", "--quiet", "--", relative_path.as_posix()], check=False)
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    raise RuntimeError("Failed to inspect staged report changes")


def _run_git(root: Path, args: Sequence[str], *, capture_output: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=capture_output,
        check=False,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return result


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
