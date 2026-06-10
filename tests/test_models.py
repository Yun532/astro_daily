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


def test_astrophysical_neutrino_paper_is_priority_topic():
    paper = Paper(
        paper_id="nu",
        title="IceCube neutrino emission from a cosmic-ray source candidate",
        abstract="We model hadronic emission from an AGN as a multimessenger high-energy neutrino source.",
        url="https://example.com/nu",
        source="arXiv",
        category="astro-ph.GA",
    )
    assert paper.is_priority_topic



def test_unrelated_neutrino_paper_is_not_priority_topic():
    paper = Paper(
        paper_id="nu-osc",
        title="Neutrino oscillation parameter constraints",
        abstract="A reactor neutrino analysis of mixing angles and mass ordering.",
        url="https://example.com/nu-osc",
        source="arXiv",
        category="hep-ex",
    )
    assert not paper.is_priority_topic



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


def test_prestige_astronomy_feed_is_priority_topic():
    paper = Paper(
        paper_id="nature-astro",
        title="Instantaneous jet power measured in an accreting black hole",
        abstract="A high-impact astronomy result.",
        url="https://example.com/nature-astro",
        source="Nature Astronomy",
    )
    assert paper.is_priority_topic


def test_prestige_journal_astronomy_article_is_priority_topic():
    paper = Paper(
        paper_id="science-astro",
        title="A gravitational wave standard siren measurement",
        abstract="The paper constrains cosmology with neutron star mergers.",
        url="https://example.com/science-astro",
        source="Science",
    )
    assert paper.is_priority_topic


def test_unrelated_prestige_journal_article_is_not_priority_topic():
    paper = Paper(
        paper_id="nature-bio",
        title="A protein structure atlas for immune signalling",
        abstract="A molecular biology resource.",
        url="https://example.com/nature-bio",
        source="Nature",
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
