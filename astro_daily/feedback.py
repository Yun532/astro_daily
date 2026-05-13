from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import re
from pathlib import Path
from typing import Any


VALID_RATINGS = {"love", "useful", "skip", "bad"}
POSITIVE_RATINGS = {"love", "useful"}
NEGATIVE_RATINGS = {"skip", "bad"}
TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+-]{2,}")
STOP_TERMS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "not",
    "that",
    "the",
    "this",
    "too",
    "with",
}


@dataclass(frozen=True)
class FeedbackRecord:
    date: date
    paper_id: str
    rating: str
    reason: str = ""
    created_at: datetime | None = None

    def to_json(self) -> dict[str, Any]:
        data = {
            "date": self.date.isoformat(),
            "paper_id": self.paper_id,
            "rating": self.rating,
            "reason": self.reason,
        }
        if self.created_at is not None:
            data["created_at"] = self.created_at.isoformat()
        return data


def append_feedback(
    path: Path,
    *,
    paper_id: str,
    rating: str,
    reason: str = "",
    feedback_date: date | None = None,
) -> FeedbackRecord:
    record = FeedbackRecord(
        date=feedback_date or date.today(),
        paper_id=_validate_paper_id(paper_id),
        rating=_validate_rating(rating),
        reason=reason.strip(),
        created_at=datetime.now(timezone.utc),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_json(), ensure_ascii=False, sort_keys=True) + "\n")
    return record


def load_feedback(path: Path, *, limit: int | None = None) -> list[FeedbackRecord]:
    if not path.exists():
        return []
    records: list[FeedbackRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            records.append(_record_from_json(raw))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid feedback record at {path}:{line_number}: {exc}") from exc
    if limit is not None:
        return records[-limit:]
    return records


def feedback_context_for_scoring(records: list[FeedbackRecord], *, recent_limit: int = 60) -> dict[str, Any]:
    recent = records[-recent_limit:]
    if not recent:
        return {}
    positive = [record for record in recent if record.rating in POSITIVE_RATINGS]
    negative = [record for record in recent if record.rating in NEGATIVE_RATINGS]
    context = {
        "instruction": (
            "Use this compact reader feedback as a soft preference signal. "
            "Boost papers similar to positive feedback when scientifically strong. "
            "Downweight papers similar to negative feedback when they are marginal. "
            "Do not let feedback override clear high-impact high-energy astrophysics results."
        ),
        "positive_paper_ids": [record.paper_id for record in positive[-12:]],
        "negative_paper_ids": [record.paper_id for record in negative[-12:]],
        "positive_terms": _top_terms(record.reason for record in positive),
        "negative_terms": _top_terms(record.reason for record in negative),
        "counts": {
            "love": sum(1 for record in recent if record.rating == "love"),
            "useful": sum(1 for record in recent if record.rating == "useful"),
            "skip": sum(1 for record in recent if record.rating == "skip"),
            "bad": sum(1 for record in recent if record.rating == "bad"),
        },
    }
    return {key: value for key, value in context.items() if value}


def _record_from_json(raw: dict[str, Any]) -> FeedbackRecord:
    return FeedbackRecord(
        date=date.fromisoformat(str(raw["date"])),
        paper_id=_validate_paper_id(str(raw["paper_id"])),
        rating=_validate_rating(str(raw["rating"])),
        reason=str(raw.get("reason", "")).strip(),
        created_at=_parse_datetime(raw.get("created_at")),
    )


def _validate_paper_id(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("paper_id must not be empty")
    return value


def _validate_rating(value: str) -> str:
    value = value.strip().lower()
    if value not in VALID_RATINGS:
        raise ValueError(f"rating must be one of: {', '.join(sorted(VALID_RATINGS))}")
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def _top_terms(reasons: Any, *, limit: int = 12) -> list[str]:
    counter: Counter[str] = Counter()
    for reason in reasons:
        for term in TERM_RE.findall(reason.casefold()):
            if term not in STOP_TERMS:
                counter[term] += 1
    return [term for term, _count in counter.most_common(limit)]
