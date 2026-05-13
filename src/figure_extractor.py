from __future__ import annotations

import logging
import shutil
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from astro_daily.config import Settings
from astro_daily.models import ExtractedFigure, FigureSelection, Paper, ScoredPaper

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FigureExtractionSummary:
    attempted: int = 0
    extracted: int = 0
    failed: int = 0


def attach_extracted_figures(scored: list[ScoredPaper], settings: Settings, *, run_date: date, analyst: Any | None = None) -> FigureExtractionSummary:
    config = settings.figure_extraction
    if not config.enabled or config.max_figures_per_paper <= 0:
        return FigureExtractionSummary()
    attempted = 0
    extracted = 0
    failed = 0
    for item in scored:
        if not item.summary:
            continue
        if not _paper_input(item.paper):
            continue
        attempted += 1
        try:
            figures = extract_figures_for_item(item, settings, run_date=run_date)
        except Exception as exc:
            failed += 1
            logger.warning("Figure extraction failed for %s: %s", item.paper.paper_id, exc)
            continue
        extracted += select_and_attach_figures(item, figures, settings, run_date=run_date, analyst=analyst)
    return FigureExtractionSummary(attempted=attempted, extracted=extracted, failed=failed)


def extract_figures_for_item(item: ScoredPaper, settings: Settings, *, run_date: date) -> list[ExtractedFigure]:
    figure_input = _paper_input(item.paper)
    if not figure_input:
        return []
    return extract_paper_figures(item.paper, settings, run_date=run_date, figure_input=figure_input)


def select_and_attach_figures(
    item: ScoredPaper,
    figures: list[ExtractedFigure],
    settings: Settings,
    *,
    run_date: date,
    analyst: Any | None,
) -> int:
    if not item.summary:
        return 0
    item.summary.extracted_figures = _select_report_figures(item, figures, settings, run_date=run_date, analyst=analyst)
    return len(item.summary.extracted_figures)


def extract_paper_figures(paper: Paper, settings: Settings, *, run_date: date, figure_input: str | None = None) -> list[ExtractedFigure]:
    config = settings.figure_extraction
    figure_input = figure_input or _paper_input(paper)
    if not figure_input:
        return []
    result = _run_paperfig(figure_input, settings)
    output_dir = Path(str(result.output_dir or ""))
    if not output_dir:
        return []
    asset_root = settings.root_dir / config.asset_dir / run_date.isoformat() / _safe_segment(paper.paper_id)
    asset_root.mkdir(parents=True, exist_ok=True)
    figures: list[ExtractedFigure] = []
    for record in result.figures[: config.max_figure_candidates_per_paper]:
        output_file = getattr(record, "output_file", None)
        if not output_file:
            continue
        source = output_dir / str(output_file)
        if not source.exists():
            continue
        target = asset_root / source.name
        shutil.copy2(source, target)
        figures.append(
            ExtractedFigure(
                fig_id=str(getattr(record, "fig_id", "") or target.stem),
                image_url=_report_relative_url(target, settings),
                caption=str(getattr(record, "caption", "") or ""),
                confidence=str(getattr(record, "confidence", "") or ""),
                source_type=str(getattr(record, "source_type", "") or ""),
                provenance=_provenance_text(getattr(record, "provenance", []) or []),
            )
        )
    return figures


def _run_paperfig(figure_input: str, settings: Settings) -> Any:
    config = settings.figure_extraction
    tool_path = Path(config.tool_path)
    if str(tool_path) not in sys.path:
        sys.path.insert(0, str(tool_path))
    from paperfig import extract_figures

    outdir = settings.root_dir / config.cache_dir / _safe_segment(figure_input)
    return extract_figures(figure_input, outdir, dpi=config.dpi, strict=config.strict)


def _select_report_figures(
    item: ScoredPaper,
    figures: list[ExtractedFigure],
    settings: Settings,
    *,
    run_date: date,
    analyst: Any | None,
) -> list[ExtractedFigure]:
    limit = settings.figure_extraction.max_figures_per_paper
    if not figures or limit <= 0:
        return []
    if not analyst or not item.summary:
        return figures[:limit]
    try:
        selections = analyst.select_figures_for_paper(
            paper=item.paper,
            summary=item.summary,
            figures=figures,
            max_figures=limit,
            run_date=run_date,
        )
    except Exception as exc:
        logger.warning("Figure selection failed for %s: %s", item.paper.paper_id, exc)
        return figures[:limit]
    selected = _apply_figure_selections(figures, selections, limit=limit)
    return selected or figures[:limit]


def _apply_figure_selections(figures: list[ExtractedFigure], selections: list[FigureSelection], *, limit: int) -> list[ExtractedFigure]:
    by_id = {figure.fig_id.casefold(): figure for figure in figures}
    selected: list[ExtractedFigure] = []
    seen: set[str] = set()
    for selection in sorted(selections, key=lambda item: item.relevance_score, reverse=True):
        key = selection.fig_id.casefold()
        figure = by_id.get(key)
        if not figure or key in seen:
            continue
        selected.append(
            figure.model_copy(
                update={
                    "related_section_cn": selection.related_section_cn,
                    "selection_reason_cn": selection.reason_cn,
                }
            )
        )
        seen.add(key)
        if len(selected) >= limit:
            break
    return selected


def _paper_input(paper: Paper) -> str | None:
    if paper.source == "arXiv":
        return paper.paper_id
    if paper.url:
        return paper.url
    return paper.pdf_url


def _report_relative_url(path: Path, settings: Settings) -> str:
    docs_dir = settings.root_dir / settings.publish.docs_dir
    relative = path.relative_to(docs_dir).as_posix()
    return "../" + relative


def _provenance_text(records: list[Any]) -> str:
    if not records:
        return ""
    first = records[0]
    source_type = getattr(first, "source_type", "")
    locator = getattr(first, "locator", "")
    return " / ".join(part for part in [str(source_type or ""), str(locator or "")] if part)


def _safe_segment(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)[:120]
