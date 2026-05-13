from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import logging

from astro_daily.llm import ClaudePaperAnalyst
from astro_daily.models import Paper, PaperSummary, ScoredPaper

logger = logging.getLogger(__name__)


def add_summaries(
    scored: list[ScoredPaper],
    analyst: ClaudePaperAnalyst,
    *,
    run_date: date,
    parallel_workers: int = 1,
) -> list[ScoredPaper]:
    summaries = _summarize_selected_papers(scored, analyst, run_date=run_date, parallel_workers=parallel_workers)
    by_id = {summary.paper_id: summary for summary in summaries}
    for item in scored:
        item.summary = by_id.get(item.paper.paper_id)
    return scored


def _summarize_selected_papers(
    scored: list[ScoredPaper],
    analyst: ClaudePaperAnalyst,
    *,
    run_date: date,
    parallel_workers: int,
) -> list[PaperSummary]:
    if not scored:
        return []
    workers = max(1, min(parallel_workers, len(scored)))
    if workers == 1:
        return [_summarize_one(item, analyst, run_date=run_date) for item in scored]
    summaries: list[PaperSummary] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_summarize_one, item, analyst, run_date=run_date): item for item in scored}
        for future in as_completed(futures):
            summaries.append(future.result())
    return summaries


def _summarize_one(item: ScoredPaper, analyst: ClaudePaperAnalyst, *, run_date: date) -> PaperSummary:
    paper = item.paper
    try:
        summaries = analyst.summarize_papers([paper], run_date=run_date)
    except RuntimeError as exc:
        logger.warning("Summary generation failed for %s; using fallback summary: %s", paper.paper_id, exc)
        return _fallback_summary(paper, reason=str(exc))
    for summary in summaries:
        if summary.paper_id == paper.paper_id:
            return summary
    if summaries:
        logger.warning(
            "Summary response for %s returned mismatched paper_id=%s; using fallback summary",
            paper.paper_id,
            summaries[0].paper_id,
        )
    else:
        logger.warning("Summary response for %s was empty; using fallback summary", paper.paper_id)
    return _fallback_summary(paper, reason="summary response did not include this paper")


def _fallback_summary(paper: Paper, *, reason: str) -> PaperSummary:
    abstract = paper.abstract or paper.title
    short_reason = reason.split("; request_type=", 1)[0]
    return PaperSummary(
        paper_id=paper.paper_id,
        title_cn=paper.title,
        summary_cn=f"本篇论文已通过推荐筛选，但自动详细解读生成失败。可先根据题目和摘要判断阅读优先级：{abstract}",
        why_important_cn="这篇论文在今日候选中通过了本地推荐阈值，说明它与当前高能天体物理兴趣方向或质量标准较匹配；详细内容建议优先查看原文摘要、结论和图表。",
        value_cn="由于 LLM 摘要 JSON 解析失败，本节保留为安全占位，不编造论文未确认的公式、图号或链接。",
        why_care_cn="日报仍保留这篇论文，是为了避免单篇摘要失败导致整份日报缺失。请把它作为需要人工快速复核的高优先级候选。",
        detailed_explanation_cn=f"自动详细解读失败，错误摘要：{short_reason}\n\n建议先阅读原文 abstract、introduction 和 conclusion，确认其核心问题、数据或模拟方法、主要结论以及与高能天体物理的关联。",
        background_cn="本节为占位背景。为了避免幻觉，系统没有在摘要失败后补写未经核实的具体背景；建议结合论文引言中的动机和相关工作继续阅读。",
        basic_theory_cn="本节为占位理论说明。建议从论文中识别核心物理量、模型假设、观测量或模拟变量，再决定是否需要展开公式推导。",
        formula_derivation_cn="本节未自动生成可靠公式推导。请以论文正文中的公式为准，避免使用未经核验的自动推导。",
        model_fitting_cn="本节未自动生成可靠模型拟合说明。请重点检查论文中的参数、似然/拟合方法、系统误差和残差诊断。",
        key_sections_cn="建议优先阅读 abstract、introduction、methods/model、results、discussion/conclusion，以及所有展示核心结论的图表。",
        figures_to_check_cn="建议检查论文中展示主要数据、模型比较、参数约束、残差或灵敏度预测的图表。",
        key_figure_analysis_cn="自动图表导读未能可靠生成。请以论文图注和正文解释为准，重点看坐标轴、样本选择、模型曲线、置信区间和系统误差。",
        related_work_cn="相关工作未能自动可靠整理。建议使用论文 introduction 和 bibliography 中反复出现的关键词检索。",
        similar_work_links=[],
        foundational_work_links=[],
        tension_or_opposing_links=[],
    )
