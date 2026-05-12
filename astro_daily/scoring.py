from __future__ import annotations

from datetime import date

from astro_daily.config import ScoringConfig
from astro_daily.models import Paper, PaperScore, ScoredPaper, ScoreResult


def prepare_candidates(papers: list[Paper], config: ScoringConfig, *, run_date: date | None = None) -> list[Paper]:
    if run_date is None:
        return _sort_candidates(papers)[: config.max_candidates]
    same_day = [paper for paper in papers if is_same_day_candidate(paper, run_date)]
    other_days = [paper for paper in papers if _is_backfill_candidate(paper, run_date)]
    candidates = _sort_candidates(same_day)
    if len(same_day) < config.same_day_target:
        candidates.extend(_sort_candidates(other_days)[: config.max_backfill_papers])
    return candidates[: config.max_candidates]


def apply_policy(
    papers: list[Paper],
    score_results: list[ScoreResult],
    config: ScoringConfig,
) -> list[ScoredPaper]:
    scored = _build_scored_papers(papers, score_results, config)
    kept = [item for item in scored if _passes_threshold(item.paper, item.score, config)]
    kept.sort(key=_scored_sort_key, reverse=True)
    return kept[: config.max_papers_per_report]


def prepare_supplemental_candidates(papers: list[Paper], config: ScoringConfig, *, run_date: date) -> list[Paper]:
    candidates = [paper for paper in papers if _is_supplemental_candidate(paper, run_date)]
    return _sort_candidates(candidates)[: config.supplemental_max_candidates]


def apply_supplemental_policy(
    papers: list[Paper],
    score_results: list[ScoreResult],
    config: ScoringConfig,
) -> list[ScoredPaper]:
    scored = [
        item
        for item in _build_scored_papers(papers, score_results, config)
        if item.score.keep
        and item.score.final_score >= config.supplemental_min_final_score
        and item.score.relevance_to_me >= config.supplemental_min_relevance
    ]
    scored.sort(key=_scored_sort_key, reverse=True)
    return scored[: config.supplemental_papers]


def paper_updated_on(paper: Paper, run_date: date) -> bool:
    return paper.updated is not None and paper.updated.date() == run_date


def is_same_day_candidate(paper: Paper, run_date: date) -> bool:
    if paper.source == "arXiv":
        return paper.source_batch_date == run_date
    return _source_available_date(paper) == run_date


def _build_scored_papers(
    papers: list[Paper],
    score_results: list[ScoreResult],
    config: ScoringConfig,
) -> list[ScoredPaper]:
    paper_by_id = {paper.paper_id: paper for paper in papers}
    scored: list[ScoredPaper] = []
    for result in score_results:
        paper = paper_by_id.get(result.paper_id)
        if not paper:
            continue
        score = PaperScore(
            novelty_score=result.novelty_score,
            importance_score=result.importance_score,
            relevance_to_me=result.relevance_to_me,
            final_score=_compute_final_score(result, paper, config),
            keep=result.keep,
            reason=result.reason,
        )
        scored.append(ScoredPaper(paper=paper, score=score))
    return scored


def _compute_final_score(score: ScoreResult, paper: Paper, config: ScoringConfig) -> float:
    weights = config.weights
    base = (
        score.novelty_score * weights.novelty
        + score.importance_score * weights.importance
        + score.relevance_to_me * weights.relevance
    )
    if paper.is_priority_topic:
        boost = config.category_boost.get(paper.category or "", config.category_boost.get("astro-ph.HE", 0.0)) * 10
    else:
        boost = config.category_boost.get(paper.category or "", 0.0) * 10
    return min(10.0, round(base + boost, 2))


def _passes_threshold(paper: Paper, score: PaperScore, config: ScoringConfig) -> bool:
    if not score.keep:
        return False
    if paper.is_priority_topic:
        return score.final_score >= config.thresholds.high_energy
    return score.final_score >= config.thresholds.non_he and score.relevance_to_me >= config.non_he_min_relevance


def _sort_candidates(papers: list[Paper]) -> list[Paper]:
    return sorted(
        papers,
        key=lambda paper: (
            1 if paper.is_priority_topic else 0,
            _paper_timestamp(paper),
        ),
        reverse=True,
    )


def _is_supplemental_candidate(paper: Paper, run_date: date) -> bool:
    if is_same_day_candidate(paper, run_date):
        return False
    paper_date = _source_available_date(paper)
    return paper_date is None or paper_date < run_date


def _scored_sort_key(item: ScoredPaper) -> tuple[float, int, str]:
    return (
        item.score.final_score,
        1 if item.paper.is_priority_topic else 0,
        _paper_timestamp(item.paper),
    )


def _paper_timestamp(paper: Paper) -> str:
    timestamp = paper.published or paper.updated
    return timestamp.isoformat() if timestamp else ""


def _source_available_date(paper: Paper) -> date | None:
    if paper.source == "arXiv" and paper.source_batch_date is not None:
        return paper.source_batch_date
    timestamp = paper.updated or paper.published
    return timestamp.date() if timestamp else None


def _is_backfill_candidate(paper: Paper, run_date: date) -> bool:
    if is_same_day_candidate(paper, run_date):
        return False
    paper_date = _source_available_date(paper)
    return paper_date is None or paper_date < run_date
