from astro_daily.models import Paper, PaperScore


def test_paper_requires_core_fields():
    paper = Paper(paper_id="1", title="  A  title  ", url="https://example.com", source="test")
    assert paper.title == "A title"


def test_iact_keywords_are_priority_topics():
    paper = Paper(
        paper_id="iact",
        title="New CTA performance study",
        abstract="A study for imaging atmospheric Cherenkov telescope analysis.",
        url="https://example.com/iact",
        source="arXiv",
        category="astro-ph.IM",
        tags=["VERITAS"],
    )
    assert paper.is_priority_topic


def test_unrelated_non_he_paper_is_not_priority_topic():
    paper = Paper(
        paper_id="co",
        title="A galaxy survey cosmology result",
        abstract="Large-scale structure constraints.",
        url="https://example.com/co",
        source="arXiv",
        category="astro-ph.CO",
    )
    assert not paper.is_priority_topic


def test_score_bounds_are_normalized():
    score = PaperScore(
        novelty_score=11,
        importance_score=5,
        relevance_to_me=0,
        final_score=5,
        keep=True,
        reason="normalized",
    )
    assert score.novelty_score == 10
    assert score.relevance_to_me == 1
