from astro_daily.config import ScoringConfig
from astro_daily.models import Paper, ScoreResult
from astro_daily.scoring import apply_policy


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
