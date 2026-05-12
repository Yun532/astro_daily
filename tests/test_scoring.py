from datetime import date, datetime, timezone

from astro_daily.config import ScoringConfig
from astro_daily.models import Paper, ScoreResult
from astro_daily.scoring import apply_policy, apply_supplemental_policy, is_same_day_candidate, paper_updated_on, prepare_candidates, prepare_supplemental_candidates


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


def test_non_he_astrophysical_neutrino_paper_gets_priority_threshold_and_boost():
    config = ScoringConfig()
    paper = make_paper("nu", "astro-ph.GA", title="IceCube high-energy neutrino source from cosmic rays")
    result = ScoreResult(
        paper_id="nu",
        novelty_score=6,
        importance_score=6,
        relevance_to_me=6,
        final_score=6,
        keep=True,
        reason="astrophysical neutrino relevant",
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
        paper.published = datetime(2026, 5, 1, tzinfo=timezone.utc)
        paper.source_batch_date = date(2026, 5, 2)
    old = make_paper("old", "astro-ph.HE")
    old.published = datetime(2026, 4, 30, tzinfo=timezone.utc)

    candidates = prepare_candidates([old, *same_day], config, run_date=date(2026, 5, 2))

    assert {paper.paper_id for paper in candidates} == {"same-0", "same-1", "same-2"}


def test_prepare_candidates_backfills_at_most_configured_old_papers_when_same_day_is_sparse():
    config = ScoringConfig(max_candidates=10, same_day_target=5, max_backfill_papers=2)
    same = make_paper("same", "astro-ph.HE")
    same.published = datetime(2026, 5, 1, tzinfo=timezone.utc)
    same.source_batch_date = date(2026, 5, 2)
    old_papers = [make_paper(f"old-{index}", "astro-ph.HE") for index in range(4)]
    for index, paper in enumerate(old_papers):
        paper.published = datetime(2026, 4, 30 - index, tzinfo=timezone.utc)
    future = make_paper("future", "astro-ph.HE")
    future.published = datetime(2026, 5, 3, tzinfo=timezone.utc)

    candidates = prepare_candidates([same, future, *old_papers], config, run_date=date(2026, 5, 2))

    assert [paper.paper_id for paper in candidates] == ["same", "old-0", "old-1"]


def test_arxiv_batch_date_marks_same_day_candidate():
    paper = make_paper("updated", "astro-ph.HE")
    paper.published = datetime(2026, 5, 11, tzinfo=timezone.utc)
    paper.updated = datetime(2026, 5, 11, tzinfo=timezone.utc)
    paper.source_batch_date = date(2026, 5, 12)

    assert is_same_day_candidate(paper, date(2026, 5, 12))
    assert not prepare_supplemental_candidates([paper], ScoringConfig(), run_date=date(2026, 5, 12))



def test_arxiv_raw_updated_date_does_not_mark_same_day_without_batch_date():
    paper = make_paper("updated", "astro-ph.HE")
    paper.published = datetime(2026, 5, 7, tzinfo=timezone.utc)
    paper.updated = datetime(2026, 5, 8, tzinfo=timezone.utc)

    assert paper_updated_on(paper, date(2026, 5, 8))
    assert not is_same_day_candidate(paper, date(2026, 5, 8))


def test_prepare_supplemental_candidates_excludes_same_day_and_future_papers():
    config = ScoringConfig(supplemental_max_candidates=10)
    updated_today = make_paper("updated-today", "astro-ph.HE")
    updated_today.published = datetime(2026, 5, 7, tzinfo=timezone.utc)
    updated_today.updated = datetime(2026, 5, 8, tzinfo=timezone.utc)
    published_today = make_paper("published-today", "astro-ph.HE")
    published_today.published = datetime(2026, 5, 8, tzinfo=timezone.utc)
    future = make_paper("future", "astro-ph.HE")
    future.published = datetime(2026, 5, 9, tzinfo=timezone.utc)
    old = make_paper("old", "astro-ph.HE")
    old.published = datetime(2026, 5, 7, tzinfo=timezone.utc)

    candidates = prepare_supplemental_candidates([updated_today, published_today, future, old], config, run_date=date(2026, 5, 8))

    assert [paper.paper_id for paper in candidates] == ["old"]


def test_apply_supplemental_policy_selects_top_high_quality_papers_below_regular_thresholds():
    config = ScoringConfig(supplemental_papers=3, supplemental_min_final_score=7.0, supplemental_min_relevance=6)
    papers = [make_paper(f"paper-{index}", "astro-ph.CO") for index in range(5)]
    results = [
        ScoreResult(paper_id="paper-0", novelty_score=7, importance_score=7, relevance_to_me=7, final_score=7, keep=True, reason="good"),
        ScoreResult(paper_id="paper-1", novelty_score=8, importance_score=8, relevance_to_me=7, final_score=8, keep=True, reason="better"),
        ScoreResult(paper_id="paper-2", novelty_score=7, importance_score=8, relevance_to_me=7, final_score=7.5, keep=True, reason="good"),
        ScoreResult(paper_id="paper-3", novelty_score=9, importance_score=9, relevance_to_me=5, final_score=9, keep=True, reason="not relevant enough"),
        ScoreResult(paper_id="paper-4", novelty_score=9, importance_score=9, relevance_to_me=9, final_score=9, keep=False, reason="LLM rejected"),
    ]

    selected = apply_supplemental_policy(papers, results, config)

    assert [item.paper.paper_id for item in selected] == ["paper-1", "paper-2", "paper-0"]
    assert apply_policy(papers, [results[0]], config) == []
