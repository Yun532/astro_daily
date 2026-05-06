from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from astro_daily.config import Settings, load_settings
from astro_daily.formula_integrity import repair_report_latex_formulas
from astro_daily.llm import ClaudePaperAnalyst
from astro_daily.models import Paper, ScoredPaper, WeekendLesson
from astro_daily.report import render_report, write_daily_report
from astro_daily.scoring import apply_policy, prepare_candidates
from astro_daily.seen import SeenStore, deduplicate_papers
from astro_daily.sources import fetch_arxiv_papers, fetch_rss_papers
from astro_daily.summarizer import add_summaries
from src.figure_extractor import attach_extracted_figures
from src.publisher import publish_report_if_enabled
from src.push_clawbot import send_clawbot_report_message
from src.push_wecom_bot import send_wecom_markdown
from src.report_html import generate_html_report
from src.report_urls import report_url
from src.wechat_summary import compress_for_wechat, compress_weekend_lessons, select_wechat_papers, wechat_category_counts

logger = logging.getLogger(__name__)

SCORE_BATCH_SIZE = 20


@dataclass
class PipelineResult:
    report_path: str
    html_report_path: str
    wechat_message: str
    wechat_selected_count: int
    wechat_he_count: int
    kept_count: int
    fetched_count: int
    new_count: int
    source_errors: list[str]
    published_url: str | None
    published: bool
    classic_lesson_count: int = 0


def run_pipeline(
    *,
    config_path: str = "config.yaml",
    run_date: date | None = None,
    dry_run: bool = False,
    ignore_seen: bool = False,
) -> PipelineResult:
    settings = load_settings(config_path)
    run_date = run_date or date.today()
    papers, source_errors = fetch_all_sources(settings)
    unique = deduplicate_papers(papers)
    seen = SeenStore.load(settings.seen_path)
    new_papers = unique if ignore_seen else seen.filter_new(unique)
    logger.info("Fetched %s papers, %s unique, %s new", len(papers), len(unique), len(new_papers))

    scored: list[ScoredPaper] = []
    weekend_lessons: list[WeekendLesson] = []
    analyst: ClaudePaperAnalyst | None = None
    if _is_weekend(run_date):
        settings.require_llm_key()
        analyst = ClaudePaperAnalyst(settings.llm, api_key=settings.anthropic_api_key or "")
        weekend_lessons = analyst.generate_weekend_lessons(
            run_date=run_date,
            topics=_weekend_classic_topics(),
            avoid_previous_lessons=seen.weekend_lesson_history(),
        )
    else:
        candidates = prepare_candidates(new_papers, settings.scoring, run_date=run_date)
        if candidates:
            settings.require_llm_key()
            analyst = ClaudePaperAnalyst(settings.llm, api_key=settings.anthropic_api_key or "")
            score_results = _score_candidates(candidates, analyst, run_date=run_date, scoring_config=settings.scoring)
            scored = apply_policy(candidates, score_results, settings.scoring)
            scored = add_summaries(scored, analyst, run_date=run_date)
            extraction = attach_extracted_figures(scored, settings, run_date=run_date, analyst=analyst)
            if extraction.attempted:
                logger.info(
                    "Figure extraction: attempted=%s extracted=%s failed=%s",
                    extraction.attempted,
                    extraction.extracted,
                    extraction.failed,
                )

    report_path = write_daily_report(
        output_dir=settings.report_dir,
        run_date=run_date,
        title_prefix=settings.report.title_prefix,
        scored_papers=scored,
        source_errors=source_errors,
        dry_run=dry_run,
        weekend_lessons=weekend_lessons,
    )
    try:
        formula_result = repair_report_latex_formulas(report_path)
        logger.info(
            "Formula integrity check: checked=%s issues=%s repaired=%s unresolved=%s",
            formula_result.checked_sections,
            formula_result.issue_count,
            formula_result.repaired_count,
            formula_result.unresolved_count,
        )
    except Exception as exc:
        logger.warning("Formula integrity check failed; continuing with original report: %s", exc)
    html_report_path = generate_html_report(str(report_path))
    publish_result = publish_report_if_enabled(settings, html_report_path, run_date, dry_run=dry_run)
    report_url_value = publish_result.url or report_url(settings.site_base_url, run_date)
    if weekend_lessons:
        wechat_message = compress_weekend_lessons(weekend_lessons, run_date.isoformat(), report_url_value)
        selected_for_wechat = weekend_lessons
        wechat_he_count = 0
    else:
        wechat_message = compress_for_wechat(scored, run_date.isoformat(), report_url_value)
        selected_for_wechat = select_wechat_papers(scored)
        wechat_he_count, _, _ = wechat_category_counts(selected_for_wechat)
    he_ratio = wechat_he_count / len(selected_for_wechat) if selected_for_wechat else 0.0
    logger.info("WeChat selected papers: %s", len(selected_for_wechat))
    logger.info("WeChat HE ratio: %.2f", he_ratio)
    logger.info("WeChat message length: %s", len(wechat_message))

    push_succeeded = dry_run or not settings.wechat.enabled
    publish_succeeded = dry_run or not settings.publish.enabled or publish_result.published or not settings.publish.require_success_before_push
    if settings.wechat.enabled:
        if dry_run:
            logger.info("Dry-run: WeCom bot push skipped")
            send_wecom_markdown(wechat_message, dry_run=True)
        else:
            send_wecom_markdown(wechat_message)
            push_succeeded = True
    if settings.clawbot.enabled and settings.clawbot.send_report:
        if dry_run:
            logger.info("Dry-run: ClawBot push skipped")
            send_clawbot_report_message(settings, wechat_message, dry_run=True)
        else:
            try:
                send_clawbot_report_message(settings, wechat_message)
            except Exception as exc:
                logger.warning("ClawBot push failed; continuing after report generation and primary publishing: %s", exc)

    if (scored or weekend_lessons) and not dry_run and push_succeeded and publish_succeeded:
        if scored:
            seen.mark_many([item.paper for item in scored], seen_date=run_date)
        if weekend_lessons:
            seen.mark_lessons(weekend_lessons, seen_date=run_date)
        seen.save()

    return PipelineResult(
        report_path=str(report_path),
        html_report_path=html_report_path,
        wechat_message=wechat_message,
        wechat_selected_count=len(selected_for_wechat),
        wechat_he_count=wechat_he_count,
        kept_count=len(scored),
        fetched_count=len(unique),
        new_count=len(new_papers),
        source_errors=source_errors,
        published_url=publish_result.url,
        published=publish_result.published,
        classic_lesson_count=len(weekend_lessons),
    )


def _score_candidates(candidates: list[Paper], analyst: ClaudePaperAnalyst, *, run_date: date, scoring_config) -> list:
    score_results = []
    for start in range(0, len(candidates), SCORE_BATCH_SIZE):
        batch = candidates[start : start + SCORE_BATCH_SIZE]
        score_results.extend(_score_batch(batch, analyst, run_date=run_date, scoring_config=scoring_config))
    return score_results


def _score_batch(batch: list[Paper], analyst: ClaudePaperAnalyst, *, run_date: date, scoring_config) -> list:
    try:
        return analyst.score_papers(batch, run_date=run_date, scoring_config=scoring_config)
    except RuntimeError:
        if len(batch) == 1:
            raise
        midpoint = len(batch) // 2
        logger.warning("LLM scoring failed for batch of %s papers; retrying as %s and %s", len(batch), midpoint, len(batch) - midpoint)
        return [
            *_score_batch(batch[:midpoint], analyst, run_date=run_date, scoring_config=scoring_config),
            *_score_batch(batch[midpoint:], analyst, run_date=run_date, scoring_config=scoring_config),
        ]


def _is_weekend(run_date: date) -> bool:
    return run_date.weekday() >= 5


def _weekend_classic_topics() -> list[str]:
    return [
        "GRB prompt emission and afterglow classic work",
        "cosmic-ray origin with SNR, PWN, pulsars, and pulsar halos",
        "IACT and TeV gamma-ray astronomy classic methods and results",
    ]


def fetch_all_sources(settings: Settings) -> tuple[list[Paper], list[str]]:
    papers: list[Paper] = []
    errors: list[str] = []
    arxiv_categories = settings.sources.arxiv.primary + settings.sources.arxiv.secondary
    for category in arxiv_categories:
        try:
            papers.extend(fetch_arxiv_papers([category], days_back=settings.sources.arxiv.days_back))
        except Exception as exc:
            message = f"arXiv {category.category}: {exc}"
            logger.warning(message)
            errors.append(message)
    for feed in settings.sources.rss.feeds:
        try:
            papers.extend(fetch_rss_papers([feed], max_entries_per_feed=settings.sources.rss.max_entries_per_feed))
        except Exception as exc:
            message = f"RSS {feed.name}: {exc}"
            logger.warning(message)
            errors.append(message)
    return papers, errors


def render_dry_wechat_message(settings: Settings) -> str:
    return render_report(
        run_date=date.today(),
        title_prefix=settings.report.title_prefix,
        scored_papers=[],
        source_errors=[],
        dry_run=True,
    )
