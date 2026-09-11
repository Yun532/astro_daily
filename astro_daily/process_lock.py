from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import time


@contextmanager
def single_process_lock(root_dir: Path, name: str, *, stale_after_seconds: float = 10800):
    lock_dir = root_dir / ".cache" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{name}.lock"
    fd: int | None = None
    try:
        fd = _acquire(lock_path, stale_after_seconds=stale_after_seconds)
        os.write(fd, f"pid={os.getpid()}\ncreated={time.time()}\n".encode("utf-8"))
        yield
    finally:
        if fd is not None:
            os.close(fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def _acquire(lock_path: Path, *, stale_after_seconds: float) -> int:
    while True:
        try:
            return os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _is_stale(lock_path, stale_after_seconds):
                try:
                    lock_path.unlink()
                    continue
                except FileNotFoundError:
                    continue
            detail = _lock_detail(lock_path)
            raise RuntimeError(f"Another Astro Daily fetch/run appears to be active ({detail}).")


def _is_stale(path: Path, stale_after_seconds: float) -> bool:
    try:
        if time.time() - path.stat().st_mtime > stale_after_seconds:
            return True
        pid = _lock_pid(path)
        if pid is not None and not _pid_is_running(pid):
            return True
        return False
    except FileNotFoundError:
        return True


def _lock_pid(path: Path) -> int | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("pid="):
                return int(line.removeprefix("pid="))
    except (OSError, ValueError):
        return None
    return None


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _lock_detail(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip().replace("\n", ", ") or str(path)
    except OSError:
        return str(path)
