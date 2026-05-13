from astro_daily.models import Paper, PaperScore, PaperSummary, ScoredPaper
from astro_daily.quality import check_summary_quality, quality_log_summary


def make_item(summary):
    return ScoredPaper(
        paper=Paper(paper_id="2605.11894", title="Paper", url="https://example.com", source="arXiv", category="astro-ph.HE"),
        score=PaperScore(novelty_score=8, importance_score=8, relevance_to_me=8, final_score=8, keep=True, reason="important"),
        summary=summary,
    )


def test_quality_flags_thin_summary():
    summary = PaperSummary(
        paper_id="2605.11894",
        title_cn="Title",
        summary_cn="short",
        why_important_cn="short",
        value_cn="short",
        why_care_cn="short",
    )

    result = check_summary_quality([make_item(summary)])[0]

    assert result.repair_needed
    assert any("too short" in issue for issue in result.issues)
    assert quality_log_summary([result])["repair_needed"] == 1


def test_quality_accepts_detailed_summary():
    long = "This section explains the concrete science context, method, result, limitation, and reading guidance. " * 5
    summary = PaperSummary(
        paper_id="2605.11894",
        title_cn="Title",
        summary_cn=long,
        why_important_cn=long,
        value_cn=long,
        why_care_cn=long,
        detailed_explanation_cn=long,
        background_cn=long,
        basic_theory_cn=long,
        formula_derivation_cn=long + "$$E=mc^2$$ and \\(F_\\nu\\propto t^{-1}\\)",
        model_fitting_cn=long,
        key_sections_cn=long,
        figures_to_check_cn=long,
        key_figure_analysis_cn=long,
        related_work_cn=long,
    )

    result = check_summary_quality([make_item(summary)])[0]

    assert not result.repair_needed
