from datetime import date

from astro_daily.models import Paper, PaperScore, PaperSummary, ScoredPaper
from astro_daily.report import render_report


def test_report_contains_summary_fields():
    paper = Paper(paper_id="1", title="A gamma-ray result", url="https://example.com", source="arXiv", category="astro-ph.HE")
    scored = ScoredPaper(
        paper=paper,
        score=PaperScore(novelty_score=8, importance_score=8, relevance_to_me=9, final_score=8.4, keep=True, reason="important"),
        summary=PaperSummary(
            paper_id="1",
            title_cn="一个伽马射线结果",
            summary_cn="它做了观测分析。",
            why_important_cn="它给出新约束。",
            value_cn="对观测有价值。",
            why_care_cn="值得关注后续样本。",
            background_cn="背景是伽马射线暴余辉偏振观测。",
            basic_theory_cn="基础理论涉及同步辐射和法拉第旋转。",
            figures_to_check_cn="建议查看光变曲线、偏振角演化和模型残差图。",
            related_work_cn="相关工作包括早期余辉偏振和磁场结构研究。",
            similar_work_links=["https://arxiv.org/abs/0000000"],
            foundational_work_links=["https://arxiv.org/abs/1111111"],
            tension_or_opposing_links=["https://arxiv.org/abs/2222222"],
        ),
    )
    report = render_report(run_date=date(2026, 5, 2), title_prefix="Astro Daily", scored_papers=[scored], source_errors=[], dry_run=True)
    assert "高能天体物理重点" in report
    assert "一个伽马射线结果" in report
    assert "<details>" in report
    assert "展开详细解读：背景、理论、图表与相关工作" in report
    assert "#### 背景知识" in report
    assert "#### 基础理论 / 方法脉络" in report
    assert "#### 建议重点查看的图表" in report
    assert "#### 强相关工作" in report
    assert "https://arxiv.org/abs/0000000" in report
    assert "Dry-run" in report


def test_report_groups_iact_papers_with_he_priority():
    paper = Paper(paper_id="2", title="CTA transient alert pipeline", url="https://example.com/2", source="arXiv", category="astro-ph.IM")
    scored = ScoredPaper(
        paper=paper,
        score=PaperScore(novelty_score=7, importance_score=7, relevance_to_me=8, final_score=8.0, keep=True, reason="IACT relevant"),
    )
    report = render_report(run_date=date(2026, 5, 2), title_prefix="Astro Daily", scored_papers=[scored], source_errors=[], dry_run=True)
    assert "高能天体物理重点" in report
    assert "相关但非 HE 的重要论文" not in report
