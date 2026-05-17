from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from astro_daily.models import ExtractedFigure, ScoredPaper, WeekendLesson


def write_daily_report(
    *,
    output_dir: Path,
    run_date: date,
    title_prefix: str,
    scored_papers: list[ScoredPaper],
    source_errors: list[str],
    dry_run: bool,
    weekend_lessons: list[WeekendLesson] | None = None,
    supplemental_papers: list[ScoredPaper] | None = None,
    classic_papers: list[ScoredPaper] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{run_date.isoformat()}.md"
    path.write_text(
        render_report(
            run_date=run_date,
            title_prefix=title_prefix,
            scored_papers=scored_papers,
            source_errors=source_errors,
            dry_run=dry_run,
            weekend_lessons=weekend_lessons,
            supplemental_papers=supplemental_papers,
            classic_papers=classic_papers,
        ),
        encoding="utf-8",
    )
    return path


def render_report(
    *,
    run_date: date,
    title_prefix: str,
    scored_papers: list[ScoredPaper],
    source_errors: list[str],
    dry_run: bool,
    weekend_lessons: list[WeekendLesson] | None = None,
    supplemental_papers: list[ScoredPaper] | None = None,
    classic_papers: list[ScoredPaper] | None = None,
) -> str:
    lines = [f"# {title_prefix} {run_date.isoformat()}", ""]
    if dry_run:
        lines.extend(["> Dry-run：本次不会推送微信，也不会更新 seen_papers.json。", ""])
    supplemental_papers = supplemental_papers or []
    classic_papers = classic_papers or []
    lines.extend(
        [
            f"生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"今日保留论文数：{len(scored_papers)}",
        ]
    )
    if scored_papers or supplemental_papers or classic_papers:
        lines.append(f"内容构成：今日新文 {len(scored_papers)} 篇；补充推荐 {len(supplemental_papers)} 篇；经典旧文精读 {len(classic_papers)} 篇")
    if supplemental_papers:
        lines.append(f"补充推荐论文数：{len(supplemental_papers)}")
    if classic_papers:
        lines.append(f"经典旧文精读数：{len(classic_papers)}")
    lines.append("")
    if source_errors:
        lines.extend(["## 数据源警告", "", *_source_warning_lines(source_errors)])
        lines.append("")
    if not scored_papers:
        if weekend_lessons:
            _append_weekend_lessons(lines, weekend_lessons)
        elif supplemental_papers or classic_papers:
            _append_fallback_papers(lines, supplemental_papers, classic_papers)
        else:
            lines.extend(
                [
                    "## 今日结论",
                    "",
                    "今天没有论文通过推荐阈值。",
                    "",
                ]
            )
        return "\n".join(lines).strip() + "\n"

    he = [item for item in scored_papers if item.paper.is_priority_topic]
    non_he = [item for item in scored_papers if not item.paper.is_priority_topic]
    _append_section(lines, "高能天体物理重点", he)
    _append_section(lines, "相关但非 HE 的重要论文", non_he)
    if supplemental_papers:
        _append_section(lines, "补充推荐：近期/较早未读论文（非今日论文）", supplemental_papers, supplemental=True)
    if classic_papers:
        _append_section(lines, "经典旧文精读：具体经典论文 / 重要旧文", classic_papers, classic=True)
    lines.extend(
        [
            "## 说明",
            "",
            "评分由 LLM 给出初评，再由本地阈值策略过滤；IACT、TeV 伽马射线和高能中微子天文学按重点方向处理。",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _append_fallback_papers(lines: list[str], supplemental_papers: list[ScoredPaper], classic_papers: list[ScoredPaper]) -> None:
    total = len(supplemental_papers) + len(classic_papers)
    lines.extend(
        [
            "## 今日结论",
            "",
            f"今天通过常规推荐阈值的新论文不足内容下限。以下 {total} 篇用于补足阅读质量：近期/较早未读论文或具体经典旧文精读，均不是今日每日论文。",
            "",
        ]
    )
    if supplemental_papers:
        lines.extend([f"今天有论文更新，但没有论文通过常规推荐阈值，或通过数量不足内容下限。以下 {len(supplemental_papers)} 篇是近期/较早未读论文中的补充推荐，不是今日每日论文。", ""])
    if supplemental_papers:
        _append_section(lines, "补充推荐：近期/较早未读论文（非今日论文）", supplemental_papers, supplemental=True)
    if classic_papers:
        _append_section(lines, "经典旧文精读：具体经典论文 / 重要旧文", classic_papers, classic=True)


def _source_warning_lines(source_errors: list[str]) -> list[str]:
    groups: dict[str, list[str]] = defaultdict(list)
    reasons: Counter[str] = Counter()
    for error in source_errors:
        group = _source_error_group(error)
        groups[group].append(error)
        reasons[_source_error_reason(error)] += 1

    lines = [
        f"- 本次有 {len(source_errors)} 个数据源访问异常；完整错误已保留在运行日志中，日报只显示摘要。",
    ]
    if groups.get("arxiv_listing"):
        lines.append(f"- arXiv 每日列表：{len(groups['arxiv_listing'])} 个分类访问异常，可能无法严格确认“今日新上架”批次。")
    if groups.get("arxiv_api"):
        lines.append(f"- arXiv API：{len(groups['arxiv_api'])} 个分类访问异常，候选池可能不完整；程序会基于已成功获取的数据继续兜底。")
    if groups.get("rss"):
        lines.append(f"- 期刊 RSS：{len(groups['rss'])} 个 feed 访问异常，主要影响 Nature/Science 等补充来源，不影响 arXiv 主流程继续生成。")
    if groups.get("other"):
        lines.append(f"- 其他来源：{len(groups['other'])} 个异常。")

    if reasons:
        reason_text = "；".join(f"{reason} {count} 次" for reason, count in reasons.most_common(3))
        lines.append(f"- 主要错误类型：{reason_text}。")
    return lines


def _source_error_group(error: str) -> str:
    if error.startswith("arXiv listing "):
        return "arxiv_listing"
    if error.startswith("arXiv "):
        return "arxiv_api"
    if error.startswith("RSS "):
        return "rss"
    return "other"


def _source_error_reason(error: str) -> str:
    lowered = error.lower()
    if "429" in lowered or "too many requests" in lowered:
        return "限流"
    if "timed out" in lowered or "timeout" in lowered:
        return "超时"
    if "ssl" in lowered or "unexpected_eof" in lowered:
        return "SSL 连接中断"
    if "connection reset" in lowered or "connection aborted" in lowered:
        return "连接中断"
    return "其他"


def _append_section(lines: list[str], title: str, papers: list[ScoredPaper], *, supplemental: bool = False, classic: bool = False) -> None:
    if not papers:
        return
    lines.extend([f"## {title}", ""])
    for index, item in enumerate(papers, start=1):
        paper = item.paper
        score = item.score
        summary = item.summary
        lines.extend(
            [
                f"### {index}. {paper.title}",
                "",
                f"- 来源：{paper.source}" + (f" / {paper.category}" if paper.category else ""),
                f"- 链接：{paper.url}",
                f"- 作者：{', '.join(paper.authors[:8]) if paper.authors else '未知'}",
            ]
        )
        if supplemental:
            lines.append("- 类型：补充推荐（近期/较早未读，非今日每日论文）")
        if classic:
            lines.append("- 类型：经典旧文精读（来自 classic_papers.yaml，非今日每日论文）")
        lines.extend(
            [
                f"- 评分：novelty {score.novelty_score}/10，importance {score.importance_score}/10，relevance {score.relevance_to_me}/10，final {score.final_score:.2f}/10",
                f"- 推荐理由：{score.reason}",
                "",
            ]
        )
        if summary:
            lines.extend(
                [
                    f"**中文题目**：{summary.title_cn}",
                    "",
                    f"**做了什么**：{summary.summary_cn}",
                    "",
                    f"**为什么重要**：{summary.why_important_cn}",
                    "",
                    f"**理论 / 观测 / 仪器方法价值**：{summary.value_cn}",
                    "",
                    f"**为什么应该关注**：{summary.why_care_cn}",
                    "",
                    '<details class="paper-detail" markdown="1">',
                    "<summary>展开详细解读：文章讲解、背景、理论、重点章节、图表与相关工作</summary>",
                    "",
                    "#### 文章详细讲解",
                    "",
                    summary.detailed_explanation_cn or "(Not provided)",
                    "",
                    "#### 背景知识",
                    "",
                    summary.background_cn or "(Not provided)",
                    "",
                    "#### 基础理论 / 方法脉络",
                    "",
                    summary.basic_theory_cn or "(Not provided)",
                    "",
                    "#### 公式与推导",
                    "",
                    summary.formula_derivation_cn or "(Not provided)",
                    "",
                    "#### 模型拟合 / 应用方法",
                    "",
                    summary.model_fitting_cn or "(Not provided)",
                    "",
                    "#### 重点章节 / 结果段落怎么读",
                    "",
                    summary.key_sections_cn or "(Not provided)",
                    "",
                    "#### 建议重点查看的图表",
                    "",
                    summary.figures_to_check_cn or "(Not provided)",
                    "",
                    "#### 关键图表逐图导读",
                    "",
                    summary.key_figure_analysis_cn or "(Not provided)",
                    "",
                    "#### 论文原图 / 可嵌入图片",
                    "",
                    *_extracted_figure_lines(summary.extracted_figures, summary.figure_image_urls),
                    "",
                    "#### 强相关工作",
                    "",
                    summary.related_work_cn or "(Not provided)",
                    "",
                    "**相似工作**：",
                    *_link_lines(summary.similar_work_links),
                    "",
                    "**基础理论 / 方法工作**：",
                    *_link_lines(summary.foundational_work_links),
                    "",
                    "**相反观点 / 张力线索**：",
                    *_link_lines(summary.tension_or_opposing_links),
                    "",
                    "</details>",
                    "",
                ]
            )
        else:
            lines.extend(["中文总结生成失败，请直接查看原文。", ""])


def _append_weekend_lessons(lines: list[str], lessons: list[WeekendLesson]) -> None:
    lines.extend(
        [
            "## 周末经典专题课",
            "",
            "周末 arXiv 通常不更新；本期改为一讲讲透的高能天体物理经典专题课，重点补公式推导、经典拟合和关键图表读法。",
            "",
        ]
    )
    for index, lesson in enumerate(lessons, start=1):
        metadata_lines = [
            line
            for line in [
                f"- 课程系列：{_lesson_series_label(lesson)}" if _lesson_series_label(lesson) else "",
                f"- 本讲边界：{lesson.lesson_scope_cn}" if lesson.lesson_scope_cn else "",
                f"- 上下文承接：{lesson.previous_context_cn}" if lesson.previous_context_cn else "",
            ]
            if line
        ]
        lines.extend(
            [
                f"### {index}. {lesson.title_cn}",
                "",
                *metadata_lines,
                f"- 主题：{lesson.topic}",
                f"- 经典工作：{lesson.anchor_work_cn}",
                f"- 为什么经典：{lesson.why_classic_cn}",
                "",
                '<details class="paper-detail" markdown="1">',
                "<summary>展开经典专题课：论文脉络、背景、理论、重点段落与图表</summary>",
                "",
                "#### 经典工作详细讲解",
                "",
                lesson.detailed_explanation_cn,
                "",
                "#### 背景知识",
                "",
                lesson.background_cn,
                "",
                "#### 基础理论 / 方法脉络",
                "",
                lesson.basic_theory_cn,
                "",
                "#### 公式与推导",
                "",
                lesson.formula_derivation_cn,
                "",
                "#### 经典拟合 / 应用方法",
                "",
                lesson.model_fitting_cn,
                "",
                "#### 重点章节 / 结果段落怎么读",
                "",
                lesson.key_sections_cn,
                "",
                "#### 建议重点查看的图表",
                "",
                lesson.figures_to_check_cn,
                "",
                "#### 关键图表逐图导读",
                "",
                lesson.key_figure_analysis_cn,
                "",
                "#### 可嵌入的官方图片",
                "",
                *_image_lines(lesson.figure_image_urls),
                "",
                "#### 后续阅读路径",
                "",
                lesson.followup_reading_cn,
                "",
                "#### 下一讲建议",
                "",
                lesson.next_lesson_suggestions_cn or "(Not provided)",
                "",
                "**检索关键词**：",
                *_link_lines(lesson.search_keywords),
                "",
                "**确信的公开链接**：",
                *_link_lines(lesson.links),
                "",
                "</details>",
                "",
            ]
        )


def _lesson_series_label(lesson: WeekendLesson) -> str:
    title = lesson.series_title_cn or lesson.series_id
    if not title:
        return ""
    if lesson.part_index and lesson.planned_parts:
        return f"{title}（第 {lesson.part_index}/{lesson.planned_parts} 讲）"
    if lesson.part_index:
        return f"{title}（第 {lesson.part_index} 讲）"
    return title


def _extracted_figure_lines(figures: list[ExtractedFigure], fallback_urls: list[str]) -> list[str]:
    if not figures:
        return _image_lines(fallback_urls)
    lines: list[str] = []
    for figure in figures:
        title = figure.fig_id or "Figure"
        lines.extend([f"**{title}**", f"![{title}]({figure.image_url})"])
        if figure.caption:
            lines.append(f"图注：{figure.caption}")
        if figure.related_section_cn:
            lines.append(f"对应解读：{figure.related_section_cn}")
        if figure.selection_reason_cn:
            lines.append(f"入选理由：{figure.selection_reason_cn}")
        provenance = "；".join(part for part in [figure.source_type, figure.confidence, figure.provenance] if part)
        if provenance:
            lines.append(f"来源与置信度：{provenance}")
        lines.append("")
    return lines[:-1]


def _image_lines(urls: list[str]) -> list[str]:
    if not urls:
        return ["（未提供 verified figure；为避免编造图片链接，本节只在能确认官方图片 URL 或成功提取论文原图时嵌入图片。）"]
    lines: list[str] = []
    for index, url in enumerate(urls, start=1):
        lines.extend([f"![关键图表 {index}]({url})", f"图源：{url}", ""])
    return lines[:-1]


def _link_lines(links: list[str]) -> list[str]:
    if not links:
        return ["（未提供）"]
    return [f"- {link}" for link in links]
