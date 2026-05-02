from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from astro_daily.models import ScoredPaper


def write_daily_report(
    *,
    output_dir: Path,
    run_date: date,
    title_prefix: str,
    scored_papers: list[ScoredPaper],
    source_errors: list[str],
    dry_run: bool,
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
) -> str:
    title = f"# {title_prefix} {run_date.isoformat()}"
    lines = [title, ""]
    if dry_run:
        lines.extend(["> Dry-run：本次不会推送微信，也不会更新 seen_papers.json。", ""])
    lines.extend([
        f"生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"今日保留论文数：{len(scored_papers)}",
        "",
    ])
    if source_errors:
        lines.extend(["## 数据源警告", ""])
        lines.extend(f"- {error}" for error in source_errors)
        lines.append("")
    if not scored_papers:
        lines.extend([
            "## 今日结论",
            "",
            "今天没有论文通过推荐阈值。不是没有新论文，而是没有看到足够值得优先阅读的结果。",
            "",
        ])
        return "\n".join(lines).strip() + "\n"

    he = [item for item in scored_papers if item.paper.is_priority_topic]
    non_he = [item for item in scored_papers if not item.paper.is_priority_topic]
    _append_section(lines, "高能天体物理重点", he)
    _append_section(lines, "相关但非 HE 的重要论文", non_he)
    lines.extend([
        "## 说明",
        "",
        "评分由 LLM 给出初评，再由本地阈值策略过滤；IACT / 大气切伦科夫望远镜相关论文按 HE 同等优先级处理，其他非 HE 论文需要明显关联高能天文、宇宙线、伽马射线或仪器/方法价值才会保留。",
        "",
    ])
    return "\n".join(lines).strip() + "\n"


def _append_section(lines: list[str], title: str, papers: list[ScoredPaper]) -> None:
    if not papers:
        return
    lines.extend([f"## {title}", ""])
    for index, item in enumerate(papers, start=1):
        paper = item.paper
        score = item.score
        summary = item.summary
        lines.extend([
            f"### {index}. {paper.title}",
            "",
            f"- 来源：{paper.source}" + (f" / {paper.category}" if paper.category else ""),
            f"- 链接：{paper.url}",
            f"- 作者：{', '.join(paper.authors[:8]) if paper.authors else '未知'}",
            f"- 评分：novelty {score.novelty_score}/10，importance {score.importance_score}/10，relevance {score.relevance_to_me}/10，final {score.final_score:.2f}/10",
            f"- 推荐理由：{score.reason}",
            "",
        ])
        if summary:
            lines.extend([
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
                "<details>",
                "<summary>展开详细解读：背景、理论、图表与相关工作</summary>",
                "",
                "#### 背景知识",
                "",
                summary.background_cn or "（未提供）",
                "",
                "#### 基础理论 / 方法脉络",
                "",
                summary.basic_theory_cn or "（未提供）",
                "",
                "#### 建议重点查看的图表",
                "",
                summary.figures_to_check_cn or "（未提供）",
                "",
                "#### 强相关工作",
                "",
                summary.related_work_cn or "（未提供）",
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
            ])
        else:
            lines.extend(["中文总结生成失败，请直接查看原文。", ""])


def _link_lines(links: list[str]) -> list[str]:
    if not links:
        return ["（未提供）"]
    return [f"- {link}" for link in links]
