from datetime import date, datetime, timezone

from astro_daily.config import ScoringConfig
from astro_daily.models import Paper, ScoreResult
from astro_daily.scoring import apply_policy, prepare_candidates


def make_paper(paper_id: str, category: str | None, title: str | None = None) -> Paper:
    return Paper(
        paper_id=paper_id,
        title=title or f"Paper {paper_id}",
        url=f"https://example.com/{paper_id}",
        source="arXiv",
        category=category,
    )


def test_he_gets_lower_threshold_and_boost():
    config = ScoringConfig()
    paper = make_paper("he", "astro-ph.HE")
    result = ScoreResult(
        paper_id="he",
        novelty_score=6,
        importance_score=6,
        relevance_to_me=6,
        final_score=6,
        keep=True,
        reason="HE relevant",
    )
    kept = apply_policy([paper], [result], config)
    assert len(kept) == 1
    assert kept[0].score.final_score == 7.0


def test_non_he_needs_stronger_score_and_relevance():
    config = ScoringConfig()
    paper = make_paper("co", "astro-ph.CO")
    result = ScoreResult(
        paper_id="co",
        novelty_score=8,
        importance_score=8,
        relevance_to_me=6,
        final_score=8,
        keep=True,
        reason="not relevant enough",
    )
    assert apply_policy([paper], [result], config) == []


def test_non_he_iact_paper_gets_priority_threshold_and_boost():
    config = ScoringConfig()
    paper = make_paper("iact", "astro-ph.IM", title="CTA observation strategy for transients")
    result = ScoreResult(
        paper_id="iact",
        novelty_score=6,
        importance_score=6,
        relevance_to_me=6,
        final_score=6,
        keep=True,
        reason="IACT relevant",
    )
    kept = apply_policy([paper], [result], config)
    assert len(kept) == 1
    assert kept[0].score.final_score == 7.0


def test_prestige_journal_source_uses_normal_non_he_threshold():
    config = ScoringConfig()
    paper = Paper(paper_id="nature", title="A transient result", url="https://example.com/nature", source="Nature", category=None)
    result = ScoreResult(
        paper_id="nature",
        novelty_score=7,
        importance_score=7,
        relevance_to_me=7,
        final_score=7,
        keep=True,
        reason="major journal astronomy result",
    )
    assert apply_policy([paper], [result], config) == []


def test_prepare_candidates_uses_only_same_day_when_enough_are_available():
    config = ScoringConfig(max_candidates=10, same_day_target=3, max_backfill_papers=5)
    same_day = [make_paper(f"same-{index}", "astro-ph.HE") for index in range(3)]
    for paper in same_day:
        paper.published = datetime(2026, 5, 2, tzinfo=timezone.utc)
    old = make_paper("old", "astro-ph.HE")
    old.published = datetime(2026, 4, 30, tzinfo=timezone.utc)

    candidates = prepare_candidates([old, *same_day], config, run_date=date(2026, 5, 2))

    assert {paper.paper_id for paper in candidates} == {"same-0", "same-1", "same-2"}


def test_prepare_candidates_backfills_at_most_configured_old_papers_when_same_day_is_sparse():
    config = ScoringConfig(max_candidates=10, same_day_target=5, max_backfill_papers=2)
    same = make_paper("same", "astro-ph.HE")
    same.published = datetime(2026, 5, 2, tzinfo=timezone.utc)
    old_papers = [make_paper(f"old-{index}", "astro-ph.HE") for index in range(4)]
    for index, paper in enumerate(old_papers):
        paper.published = datetime(2026, 4, 30 - index, tzinfo=timezone.utc)
    future = make_paper("future", "astro-ph.HE")
    future.published = datetime(2026, 5, 3, tzinfo=timezone.utc)

    candidates = prepare_candidates([same, future, *old_papers], config, run_date=date(2026, 5, 2))

    assert [paper.paper_id for paper in candidates] == ["same", "old-0", "old-1"]
