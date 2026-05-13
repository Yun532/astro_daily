from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator
from uuid import uuid4


class RunLogger:
    def __init__(self, *, root_dir: Path, log_dir: str, run_date: date, enabled: bool = True):
        self.enabled = enabled
        self.run_date = run_date
        self.run_id = uuid4().hex[:12]
        self.path = root_dir / log_dir / f"pipeline-{run_date.isoformat()}-{self.run_id}.jsonl"
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, stage: str, event: str, **data: Any) -> None:
        if not self.enabled:
            return
        record = {
            "run_id": self.run_id,
            "run_date": self.run_date.isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "event": event,
        }
        if data:
            record["data"] = _json_safe(data)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    @contextmanager
    def stage(self, name: str, **start_data: Any) -> Iterator[dict[str, Any]]:
        result: dict[str, Any] = {}
        start = perf_counter()
        self.event(name, "start", **start_data)
        try:
            yield result
        except Exception as exc:
            self.event(
                name,
                "error",
                duration_seconds=round(perf_counter() - start, 3),
                error_type=type(exc).__name__,
                error_message=str(exc),
                **result,
            )
            raise
        self.event(name, "end", duration_seconds=round(perf_counter() - start, 3), **result)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)
