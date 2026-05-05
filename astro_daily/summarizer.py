from __future__ import annotations

from datetime import date

from astro_daily.llm import ClaudePaperAnalyst
from astro_daily.models import PaperSummary, ScoredPaper

SUMMARY_BATCH_SIZE = 4


def add_summaries(scored: list[ScoredPaper], analyst: ClaudePaperAnalyst, *, run_date: date) -> list[ScoredPaper]:
    summaries: list[PaperSummary] = []
    for start in range(0, len(scored), SUMMARY_BATCH_SIZE):
        batch = scored[start : start + SUMMARY_BATCH_SIZE]
        summaries.extend(_summarize_batch(batch, analyst, run_date=run_date))
    by_id = {summary.paper_id: summary for summary in summaries}
    for item in scored:
        item.summary = by_id.get(item.paper.paper_id)
    return scored


def _summarize_batch(batch: list[ScoredPaper], analyst: ClaudePaperAnalyst, *, run_date: date) -> list[PaperSummary]:
    try:
        return analyst.summarize_papers([item.paper for item in batch], run_date=run_date)
    except RuntimeError:
        if len(batch) == 1:
            raise
        midpoint = len(batch) // 2
        return [
            *_summarize_batch(batch[:midpoint], analyst, run_date=run_date),
            *_summarize_batch(batch[midpoint:], analyst, run_date=run_date),
        ]
