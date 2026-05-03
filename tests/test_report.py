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
            detailed_explanation_cn="文章详细解释了科学问题、观测方法和关键结果。",
            background_cn="背景是伽马射线暴余辉偏振观测。",
            basic_theory_cn="基础理论涉及同步辐射和法拉第旋转。",
            formula_derivation_cn="关键公式为 $$F_\\nu \\propto t^{-\\alpha}\\nu^{-\\beta}$$，用于连接光变和谱指数。",
            model_fitting_cn="拟合时重点看光变模型、偏振角演化和残差结构。",
            key_sections_cn="重点阅读样本、方法和结果章节。",
            figures_to_check_cn="建议查看光变曲线、偏振角演化和模型残差图。",
            key_figure_analysis_cn="图 1 看光变曲线斜率，图 2 看模型残差。",
            figure_image_urls=["https://example.com/figure.png"],
            related_work_cn="相关工作包括早期余辉偏振和磁场结构研究。",
            similar_work_links=["https://arxiv.org/abs/0000000"],
            foundational_work_links=["https://arxiv.org/abs/1111111"],
            tension_or_opposing_links=["https://arxiv.org/abs/2222222"],
        ),
    )
    report = render_report(run_date=date(2026, 5, 2), title_prefix="Astro Daily", scored_papers=[scored], source_errors=[], dry_run=True)
    assert "高能天体物理重点" in report
    assert "一个伽马射线结果" in report
    assert "<details class=\"paper-detail\" markdown=\"1\">" in report
    assert "展开详细解读：文章讲解、背景、理论、重点章节、图表与相关工作" in report
    assert "#### 文章详细讲解" in report
    assert "#### 背景知识" in report
    assert "#### 基础理论 / 方法脉络" in report
    assert "#### 公式与推导" in report
    assert "F_\\nu" in report
    assert "#### 模型拟合 / 应用方法" in report
    assert "#### 重点章节 / 结果段落怎么读" in report
    assert "#### 建议重点查看的图表" in report
    assert "#### 关键图表逐图导读" in report
    assert "![关键图表 1](https://example.com/figure.png)" in report
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


def test_report_renders_weekend_classic_lessons_when_no_papers():
    from astro_daily.models import WeekendLesson

    lesson = WeekendLesson(
        topic="GRB",
        title_cn="GRB 余辉经典专题",
        anchor_work_cn="GRB afterglow classic work",
        why_classic_cn="它建立了余辉火球模型的基本读法。",
        detailed_explanation_cn="详细讲解科学问题、方法、关键结果和后续影响。",
        background_cn="背景知识解释爆发、余辉和观测历史。",
        basic_theory_cn="基础理论涉及相对论激波和同步辐射。",
        formula_derivation_cn="从能量守恒得到 $$E \\sim \\Gamma^2 M c^2$$，再推出减速时间。",
        model_fitting_cn="经典拟合包括宽带余辉 SED、closure relation 和 jet break。",
        key_sections_cn="重点阅读模型假设、光变曲线和谱演化。",
        figures_to_check_cn="建议查看光变曲线、谱能量分布和参数退化图。",
        key_figure_analysis_cn="图 1 看多波段光变，图 2 看谱断裂，图 3 看残差。",
        figure_image_urls=[],
        followup_reading_cn="后续阅读可以从余辉模型读到喷流破裂和多信使观测。",
        search_keywords=["GRB afterglow fireball model"],
        links=[],
    )

    report = render_report(
        run_date=date(2026, 5, 2),
        title_prefix="Astro Daily",
        scored_papers=[],
        source_errors=[],
        dry_run=True,
        weekend_lessons=[lesson],
    )

    assert "周末经典专题课" in report
    assert "GRB 余辉经典专题" in report
    assert "展开经典专题课" in report
    assert "#### 公式与推导" in report
    assert "E \\sim" in report
    assert "#### 经典拟合 / 应用方法" in report
    assert "#### 关键图表逐图导读" in report
    assert "避免编造图片链接" in report
    assert "GRB afterglow fireball model" in report
    assert "今天没有论文通过推荐阈值" not in report
