from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import re
import shutil
import stat

from astro_daily.config import Settings

DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class CleanupResult:
    dry_run: bool
    cache_removed_count: int
    cache_removed_bytes: int
    asset_removed_count: int
    asset_removed_bytes: int
    kept_asset_dates: list[str]
    removed_paths: list[str]
    failed_paths: list[str]

    @property
    def total_removed_bytes(self) -> int:
        return self.cache_removed_bytes + self.asset_removed_bytes

    def to_log_data(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "cache_removed_count": self.cache_removed_count,
            "cache_removed_mb": round(self.cache_removed_bytes / 1024 / 1024, 2),
            "asset_removed_count": self.asset_removed_count,
            "asset_removed_mb": round(self.asset_removed_bytes / 1024 / 1024, 2),
            "total_removed_mb": round(self.total_removed_bytes / 1024 / 1024, 2),
            "kept_asset_dates": self.kept_asset_dates,
            "removed_paths": self.removed_paths[:50],
            "failed_count": len(self.failed_paths),
            "failed_paths": self.failed_paths[:50],
        }


def cleanup_runtime_artifacts(settings: Settings, *, run_date: date, dry_run: bool = False) -> CleanupResult:
    root = settings.root_dir.resolve()
    removed_paths: list[str] = []
    failed_paths: list[str] = []
    cache_removed_count = 0
    cache_removed_bytes = 0
    asset_removed_count = 0
    asset_removed_bytes = 0

    cache_root = (settings.root_dir / settings.figure_extraction.cache_dir).resolve()
    if _is_relative_to(cache_root, root) and cache_root.exists():
        cutoff = datetime.combine(run_date, datetime.min.time()) - timedelta(days=settings.maintenance.figure_cache_retention_days)
        for path in _child_dirs(cache_root):
            if datetime.fromtimestamp(path.stat().st_mtime) >= cutoff:
                continue
            size = _path_size(path)
            try:
                _remove_tree(path, root=root, dry_run=dry_run)
            except OSError:
                failed_paths.append(_display_path(path, root))
                continue
            cache_removed_count += 1
            cache_removed_bytes += size
            removed_paths.append(_display_path(path, root))

    asset_root = (settings.root_dir / settings.figure_extraction.asset_dir).resolve()
    kept_asset_dates: list[str] = []
    if _is_relative_to(asset_root, root) and asset_root.exists():
        date_dirs = [path for path in _child_dirs(asset_root) if DATE_DIR_RE.fullmatch(path.name)]
        date_dirs.sort(key=lambda path: path.name)
        keep_count = settings.maintenance.figure_asset_keep_recent_dates
        keep = set(date_dirs[-keep_count:])
        kept_asset_dates = [path.name for path in date_dirs[-keep_count:]]
        for path in date_dirs:
            if path in keep:
                continue
            size = _path_size(path)
            try:
                _remove_tree(path, root=root, dry_run=dry_run)
            except OSError:
                failed_paths.append(_display_path(path, root))
                continue
            asset_removed_count += 1
            asset_removed_bytes += size
            removed_paths.append(_display_path(path, root))

    return CleanupResult(
        dry_run=dry_run,
        cache_removed_count=cache_removed_count,
        cache_removed_bytes=cache_removed_bytes,
        asset_removed_count=asset_removed_count,
        asset_removed_bytes=asset_removed_bytes,
        kept_asset_dates=kept_asset_dates,
        removed_paths=removed_paths,
        failed_paths=failed_paths,
    )


def _child_dirs(path: Path) -> list[Path]:
    return [child for child in path.iterdir() if child.is_dir()]


def _path_size(path: Path) -> int:
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def _remove_tree(path: Path, *, root: Path, dry_run: bool) -> None:
    resolved = path.resolve()
    if not _is_relative_to(resolved, root):
        raise RuntimeError(f"Refusing to remove path outside repository root: {resolved}")
    if dry_run:
        return
    shutil.rmtree(resolved, onerror=_handle_remove_readonly)


def _handle_remove_readonly(function, path: str, _exc_info) -> None:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    function(path)


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
