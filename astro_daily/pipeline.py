from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import logging
import time
from dataclasses import dataclass
from datetime import date

from astro_daily.config import Settings, load_settings
from astro_daily.feedback import feedback_context_for_scoring, load_feedback
from astro_daily.formula_integrity import ensure_html_latex_formulas_valid, repair_report_latex_formulas
from astro_daily.llm import ClaudePaperAnalyst
from astro_daily.models import Paper, ScoredPaper, WeekendLesson
from astro_daily.quality import check_summary_quality, quality_log_summary
from astro_daily.report import render_report, write_daily_report
from astro_daily.run_logging import RunLogger
from astro_daily.scoring import (
    apply_policy,
    apply_supplemental_policy,
    is_same_day_candidate,
    prepare_candidates,
    prepare_supplemental_candidates,
)
from astro_daily.seen import SeenStore, deduplicate_papers
from astro_daily.sources import fetch_arxiv_papers, fetch_rss_papers
from astro_daily.sources.arxiv import ArxivDailyListing, fetch_arxiv_daily_listing
from astro_daily.summarizer import add_summaries
from src.figure_extractor import FigureExtractionSummary, attach_extracted_figures, extract_figures_for_item, select_and_attach_figures
from src.publisher import publish_report_if_enabled
from src.push_clawbot import send_clawbot_report_message
from src.push_wecom_bot import send_wecom_markdown
from src.report_html import generate_html_report
from src.report_urls import report_url
from src.wechat_summary import compress_for_wechat, compress_weekend_lessons, select_wechat_papers, wechat_category_counts

logger = logging.getLogger(__name__)

SCORE_BATCH_SIZE = 20
DEFERRED_RETRY_EXIT_CODE = 75
TEMPORARY_SOURCE_ERROR_MARKERS = (
    "429",
    "503",
    "timeout",
    "timed out",
    "read timed out",
    "connection timeout",
    "connection aborted",
    "connection reset",
    "temporarily unavailable",
)


class DeferredRetryNeeded(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceFreshnessDecision:
    should_defer: bool
    reason: str
    primary_today_count: int
    transient_primary_errors: list[str]
    primary_batch_confirmed: bool = False


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
    supplemental_count: int = 0


def run_pipeline(
    *,
    config_path: str = "config.yaml",
    run_date: date | None = None,
    dry_run: bool = False,
    ignore_seen: bool = False,
    defer_if_unfresh: bool = False,
    final_attempt: bool = False,
) -> PipelineResult:
    settings = load_settings(config_path)
    run_date = run_date or date.today()
    run_logger = RunLogger(root_dir=settings.root_dir, log_dir=settings.run_log.dir, run_date=run_date, enabled=settings.run_log.enabled)
    run_logger.event(
        "pipeline",
        "start",
        dry_run=dry_run,
        ignore_seen=ignore_seen,
        defer_if_unfresh=defer_if_unfresh,
        final_attempt=final_attempt,
    )

    with run_logger.stage("fetch_sources") as stage:
        papers, source_errors = fetch_all_sources(settings)
        stage.update(fetched_count=len(papers), source_error_count=len(source_errors), source_errors=source_errors)
    with run_logger.stage("deduplicate", input_count=len(papers)) as stage:
        unique = deduplicate_papers(papers)
        stage["unique_count"] = len(unique)
    with run_logger.stage("source_freshness") as stage:
        freshness = evaluate_source_freshness(settings=settings, papers=unique, source_errors=source_errors, run_date=run_date)
        stage.update(_freshness_log_data(freshness))
    logger.info(
        "Source freshness: primary_today=%s primary_batch_confirmed=%s transient_primary_errors=%s defer=%s",
        freshness.primary_today_count,
        freshness.primary_batch_confirmed,
        len(freshness.transient_primary_errors),
        freshness.should_defer,
    )
    if defer_if_unfresh and not final_attempt and freshness.should_defer:
        run_logger.event("source_freshness", "defer", reason=freshness.reason)
        raise DeferredRetryNeeded(freshness.reason)
    with run_logger.stage("seen_filter", ignore_seen=ignore_seen) as stage:
        seen = SeenStore.load(settings.seen_path)
        new_papers = unique if ignore_seen else seen.filter_new(unique)
        stage.update(unique_count=len(unique), new_count=len(new_papers))
    with run_logger.stage("feedback_load") as stage:
        try:
            feedback_records = load_feedback(settings.feedback_path, limit=200)
        except ValueError as exc:
            logger.warning("Feedback file could not be loaded; continuing without feedback: %s", exc)
            feedback_records = []
            stage["error"] = str(exc)
        feedback_context = feedback_context_for_scoring(feedback_records)
        stage.update(
            feedback_count=len(feedback_records),
            positive_terms=feedback_context.get("positive_terms", []),
            negative_terms=feedback_context.get("negative_terms", []),
        )
    logger.info("Fetched %s papers, %s unique, %s new", len(papers), len(unique), len(new_papers))

    scored: list[ScoredPaper] = []
    supplemental_scored: list[ScoredPaper] = []
    weekend_lessons: list[WeekendLesson] = []
    analyst: ClaudePaperAnalyst | None = None
    if _is_weekend(run_date):
        with run_logger.stage("weekend_lessons") as stage:
            settings.require_llm_key()
            analyst = ClaudePaperAnalyst(settings.llm, api_key=settings.anthropic_api_key or "")
            weekend_lessons = analyst.generate_weekend_lessons(
                run_date=run_date,
                topics=_weekend_classic_topics(),
                avoid_previous_lessons=seen.weekend_lesson_history(),
            )
            stage.update(classic_lesson_count=len(weekend_lessons), titles=[lesson.title_cn for lesson in weekend_lessons])
    else:
        with run_logger.stage("prepare_candidates") as stage:
            candidates = prepare_candidates(new_papers, settings.scoring, run_date=run_date)
            today_update_exists = any(_paper_available_on(paper, run_date) for paper in new_papers)
            stage.update(
                candidate_count=len(candidates),
                same_day_candidate_count=sum(1 for paper in candidates if is_same_day_candidate(paper, run_date)),
                today_update_exists=today_update_exists,
            )
        if candidates:
            settings.require_llm_key()
            analyst = ClaudePaperAnalyst(settings.llm, api_key=settings.anthropic_api_key or "")
            with run_logger.stage("score_candidates", candidate_count=len(candidates), score_batch_size=SCORE_BATCH_SIZE) as stage:
                score_results = _score_candidates(candidates, analyst, run_date=run_date, scoring_config=settings.scoring, feedback_context=feedback_context)
                stage.update(score_result_count=len(score_results), score_batch_count=(len(candidates) + SCORE_BATCH_SIZE - 1) // SCORE_BATCH_SIZE)
            with run_logger.stage("apply_policy") as stage:
                scored = apply_policy(candidates, score_results, settings.scoring)
                stage.update(regular_threshold_passing_count=len(scored), selected_papers=_scored_log_items(scored))
            if not scored and (today_update_exists or final_attempt):
                with run_logger.stage("supplemental_selection") as stage:
                    supplemental_scored = _select_supplemental_papers(
                        new_papers,
                        score_results,
                        analyst,
                        run_date=run_date,
                        scoring_config=settings.scoring,
                        feedback_context=feedback_context,
                    )
                    stage.update(supplemental_selected_count=len(supplemental_scored), selected_papers=_scored_log_items(supplemental_scored))
            displayed_scored = scored or supplemental_scored
            with run_logger.stage(
                "summaries_and_figures",
                paper_count=len(displayed_scored),
                summary_parallel_workers=settings.llm.summary_parallel_workers,
                figure_parallel_workers=settings.figure_extraction.parallel_workers,
            ) as stage:
                displayed_scored, extraction = _enrich_selected_papers(displayed_scored, settings, analyst, run_date=run_date)
                quality_results = check_summary_quality(displayed_scored)
                stage.update(
                    summary_count=sum(1 for item in displayed_scored if item.summary),
                    figure_attempted=extraction.attempted,
                    figure_extracted=extraction.extracted,
                    figure_failed=extraction.failed,
                    content_quality=quality_log_summary(quality_results),
                )
            if scored:
                scored = displayed_scored
            else:
                supplemental_scored = displayed_scored
            if extraction.attempted:
                logger.info(
                    "Figure extraction: attempted=%s extracted=%s failed=%s",
                    extraction.attempted,
                    extraction.extracted,
                    extraction.failed,
                )

    with run_logger.stage("write_markdown_report") as stage:
        report_path = write_daily_report(
            output_dir=settings.report_dir,
            run_date=run_date,
            title_prefix=settings.report.title_prefix,
            scored_papers=scored,
            source_errors=source_errors,
            dry_run=dry_run,
            weekend_lessons=weekend_lessons,
            supplemental_papers=supplemental_scored,
        )
        stage["report_path"] = str(report_path)
    try:
        with run_logger.stage("formula_repair") as stage:
            formula_result = repair_report_latex_formulas(report_path)
            stage.update(_formula_result_log_data(formula_result))
            logger.info(
                "Formula integrity check: checked=%s issues=%s repaired=%s unresolved=%s",
                formula_result.checked_sections,
                formula_result.issue_count,
                formula_result.repaired_count,
                formula_result.unresolved_count,
            )
    except Exception as exc:
        logger.warning("Formula integrity check failed; continuing with original report: %s", exc)
    with run_logger.stage("html_generation") as stage:
        html_report_path = generate_html_report(str(report_path))
        stage["html_report_path"] = html_report_path
    with run_logger.stage("html_formula_validation") as stage:
        html_formula_result = ensure_html_latex_formulas_valid(html_report_path)
        stage.update(_formula_result_log_data(html_formula_result))
    logger.info("HTML formula validation: checked=%s issues=%s", html_formula_result.checked_sections, html_formula_result.issue_count)
    with run_logger.stage("publish", dry_run=dry_run) as stage:
        publish_result = publish_report_if_enabled(settings, html_report_path, run_date, dry_run=dry_run)
        stage.update(published=publish_result.published, published_url=publish_result.url)
    report_url_value = publish_result.url or report_url(settings.site_base_url, run_date)
    with run_logger.stage("wechat_compression") as stage:
        if weekend_lessons:
            wechat_message = compress_weekend_lessons(weekend_lessons, run_date.isoformat(), report_url_value)
            selected_for_wechat = weekend_lessons
            wechat_he_count = 0
        elif supplemental_scored:
            wechat_message = compress_for_wechat(supplemental_scored, run_date.isoformat(), report_url_value, supplemental=True)
            selected_for_wechat = select_wechat_papers(supplemental_scored, supplemental=True)
            wechat_he_count, _, _ = wechat_category_counts(selected_for_wechat)
        else:
            wechat_message = compress_for_wechat(scored, run_date.isoformat(), report_url_value)
            selected_for_wechat = select_wechat_papers(scored)
            wechat_he_count, _, _ = wechat_category_counts(selected_for_wechat)
        he_ratio = wechat_he_count / len(selected_for_wechat) if selected_for_wechat else 0.0
        stage.update(wechat_selected_count=len(selected_for_wechat), wechat_he_count=wechat_he_count, wechat_message_length=len(wechat_message))
    logger.info("WeChat selected papers: %s", len(selected_for_wechat))
    logger.info("WeChat HE ratio: %.2f", he_ratio)
    logger.info("WeChat message length: %s", len(wechat_message))

    push_succeeded = dry_run or not settings.wechat.enabled
    publish_succeeded = dry_run or not settings.publish.enabled or publish_result.published or not settings.publish.require_success_before_push
    with run_logger.stage("push", dry_run=dry_run) as stage:
        if settings.wechat.enabled:
            if dry_run:
                logger.info("Dry-run: WeCom bot push skipped")
                send_wecom_markdown(wechat_message, dry_run=True)
                stage["wecom"] = "dry_run"
            else:
                send_wecom_markdown(wechat_message)
                push_succeeded = True
                stage["wecom"] = "sent"
        else:
            stage["wecom"] = "disabled"
        if settings.clawbot.enabled and settings.clawbot.send_report:
            if dry_run:
                logger.info("Dry-run: ClawBot push skipped")
                send_clawbot_report_message(settings, wechat_message, dry_run=True)
                stage["clawbot"] = "dry_run"
            else:
                try:
                    send_clawbot_report_message(settings, wechat_message)
                    stage["clawbot"] = "sent"
                except Exception as exc:
                    stage["clawbot"] = f"failed: {exc}"
                    logger.warning("ClawBot push failed; continuing after report generation and primary publishing: %s", exc)
        else:
            stage["clawbot"] = "disabled"
        stage.update(push_succeeded=push_succeeded, publish_succeeded=publish_succeeded)

    displayed_papers = scored or supplemental_scored
    with run_logger.stage("seen_update", dry_run=dry_run) as stage:
        should_update_seen = bool((displayed_papers or weekend_lessons) and not dry_run and push_succeeded and publish_succeeded)
        stage["updated"] = should_update_seen
        if should_update_seen:
            if displayed_papers:
                seen.mark_many([item.paper for item in displayed_papers], seen_date=run_date)
            if weekend_lessons:
                seen.mark_lessons(weekend_lessons, seen_date=run_date)
            seen.save()
        else:
            stage["reason"] = _seen_skip_reason(displayed_papers, weekend_lessons, dry_run, push_succeeded, publish_succeeded)

    result = PipelineResult(
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
        supplemental_count=len(supplemental_scored),
    )
    run_logger.event(
        "pipeline",
        "end",
        kept_count=result.kept_count,
        supplemental_count=result.supplemental_count,
        classic_lesson_count=result.classic_lesson_count,
        report_path=result.report_path,
        html_report_path=result.html_report_path,
    )
    return result


def _enrich_selected_papers(
    scored: list[ScoredPaper],
    settings: Settings,
    analyst: ClaudePaperAnalyst,
    *,
    run_date: date,
) -> tuple[list[ScoredPaper], FigureExtractionSummary]:
    if not scored:
        return scored, FigureExtractionSummary()
    executor: ThreadPoolExecutor | None = None
    futures: dict[Future[list], ScoredPaper] = {}
    attempted = 0
    if settings.figure_extraction.enabled and settings.figure_extraction.max_figures_per_paper > 0:
        extractable = [item for item in scored if item.paper.source == "arXiv" or item.paper.url or item.paper.pdf_url]
        if extractable:
            attempted = len(extractable)
            workers = min(settings.figure_extraction.parallel_workers, len(extractable))
            executor = ThreadPoolExecutor(max_workers=workers)
            futures = {executor.submit(extract_figures_for_item, item, settings, run_date=run_date): item for item in extractable}
    try:
        scored = add_summaries(scored, analyst, run_date=run_date, parallel_workers=settings.llm.summary_parallel_workers)
        if not futures:
            return scored, FigureExtractionSummary()
        ready_for_selection: list[tuple[ScoredPaper, list]] = []
        failed = 0
        for future in as_completed(futures):
            item = futures[future]
            try:
                figures = future.result()
            except Exception as exc:
                failed += 1
                logger.warning("Figure extraction failed for %s: %s", item.paper.paper_id, exc)
                continue
            ready_for_selection.append((item, figures))
        extracted = _select_figures_for_items_parallel(ready_for_selection, settings, analyst, run_date=run_date)
        return scored, FigureExtractionSummary(attempted=attempted, extracted=extracted, failed=failed)
    finally:
        if executor:
            executor.shutdown(wait=True)


def _select_figures_for_items_parallel(
    items: list[tuple[ScoredPaper, list]],
    settings: Settings,
    analyst: ClaudePaperAnalyst,
    *,
    run_date: date,
) -> int:
    if not items:
        return 0
    workers = min(settings.figure_extraction.parallel_workers, len(items))
    if workers <= 1:
        return sum(select_and_attach_figures(item, figures, settings, run_date=run_date, analyst=analyst) for item, figures in items)
    extracted = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(select_and_attach_figures, item, figures, settings, run_date=run_date, analyst=analyst): item
            for item, figures in items
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                extracted += future.result()
            except Exception as exc:
                logger.warning("Figure selection failed for %s: %s", item.paper.paper_id, exc)
    return extracted


def _freshness_log_data(freshness: SourceFreshnessDecision) -> dict[str, object]:
    return {
        "should_defer": freshness.should_defer,
        "reason": freshness.reason,
        "primary_today_count": freshness.primary_today_count,
        "transient_primary_error_count": len(freshness.transient_primary_errors),
        "transient_primary_errors": freshness.transient_primary_errors,
        "primary_batch_confirmed": freshness.primary_batch_confirmed,
    }


def _scored_log_items(scored: list[ScoredPaper]) -> list[dict[str, object]]:
    return [
        {
            "paper_id": item.paper.paper_id,
            "title": item.paper.title,
            "source": item.paper.source,
            "category": item.paper.category,
            "published": item.paper.published.isoformat() if item.paper.published else None,
            "updated": item.paper.updated.isoformat() if item.paper.updated else None,
            "source_batch_date": item.paper.source_batch_date.isoformat() if item.paper.source_batch_date else None,
            "final_score": item.score.final_score,
            "relevance_to_me": item.score.relevance_to_me,
        }
        for item in scored
    ]


def _formula_result_log_data(result) -> dict[str, object]:
    return {
        "checked_sections": result.checked_sections,
        "issue_count": result.issue_count,
        "repaired_count": getattr(result, "repaired_count", 0),
        "unresolved_count": getattr(result, "unresolved_count", 0),
    }


def _seen_skip_reason(
    displayed_papers: list[ScoredPaper],
    weekend_lessons: list[WeekendLesson],
    dry_run: bool,
    push_succeeded: bool,
    publish_succeeded: bool,
) -> str:
    if dry_run:
        return "dry_run"
    if not displayed_papers and not weekend_lessons:
        return "nothing_to_mark"
    if not push_succeeded:
        return "push_not_confirmed"
    if not publish_succeeded:
        return "publish_not_confirmed"
    return "unknown"


def evaluate_source_freshness(*, settings: Settings, papers: list[Paper], source_errors: list[str], run_date: date) -> SourceFreshnessDecision:
    if _is_weekend(run_date):
        return SourceFreshnessDecision(False, "weekend run does not defer for arXiv freshness", 0, [])
    primary_categories = {category.category for category in settings.sources.arxiv.primary}
    primary_today_count = sum(
        1
        for paper in papers
        if paper.source == "arXiv" and paper.category in primary_categories and paper.source_batch_date == run_date
    )
    primary_batch_confirmed = primary_today_count > 0
    transient_primary_errors = [
        error
        for error in source_errors
        if _is_primary_arxiv_error(error, primary_categories) and _is_temporary_source_error(error)
    ]
    if transient_primary_errors:
        return SourceFreshnessDecision(
            True,
            "temporary primary arXiv source error: " + "; ".join(transient_primary_errors),
            primary_today_count,
            transient_primary_errors,
            primary_batch_confirmed,
        )
    if primary_categories and not primary_batch_confirmed:
        return SourceFreshnessDecision(
            True,
            "primary arXiv daily listing is not confirmed for the report date; arXiv may not have updated yet",
            primary_today_count,
            transient_primary_errors,
            primary_batch_confirmed,
        )
    return SourceFreshnessDecision(False, "primary arXiv daily listing is confirmed", primary_today_count, transient_primary_errors, primary_batch_confirmed)



def _score_candidates(
    candidates: list[Paper],
    analyst: ClaudePaperAnalyst,
    *,
    run_date: date,
    scoring_config,
    feedback_context: dict | None = None,
) -> list:
    score_results = []
    for start in range(0, len(candidates), SCORE_BATCH_SIZE):
        batch = candidates[start : start + SCORE_BATCH_SIZE]
        score_results.extend(_score_batch(batch, analyst, run_date=run_date, scoring_config=scoring_config, feedback_context=feedback_context))
    return score_results


def _paper_available_on(paper: Paper, run_date: date) -> bool:
    return is_same_day_candidate(paper, run_date)


def _is_primary_arxiv_error(error: str, primary_categories: set[str]) -> bool:
    return error.startswith("arXiv ") and any(category in error for category in primary_categories)


def _is_temporary_source_error(error: str) -> bool:
    lowered = error.lower()
    return any(marker in lowered for marker in TEMPORARY_SOURCE_ERROR_MARKERS)


def _select_supplemental_papers(
    new_papers: list[Paper],
    existing_score_results: list,
    analyst: ClaudePaperAnalyst,
    *,
    run_date: date,
    scoring_config,
    feedback_context: dict | None = None,
) -> list[ScoredPaper]:
    candidates = prepare_supplemental_candidates(new_papers, scoring_config, run_date=run_date)
    if not candidates:
        return []
    existing_by_id = {result.paper_id: result for result in existing_score_results}
    missing_candidates = [paper for paper in candidates if paper.paper_id not in existing_by_id]
    score_results = [existing_by_id[paper.paper_id] for paper in candidates if paper.paper_id in existing_by_id]
    if missing_candidates:
        score_results.extend(
            _score_candidates(
                missing_candidates,
                analyst,
                run_date=run_date,
                scoring_config=scoring_config,
                feedback_context=feedback_context,
            )
        )
    supplemental = apply_supplemental_policy(candidates, score_results, scoring_config)
    logger.info("Supplemental fallback selected %s papers", len(supplemental))
    return supplemental


def _score_batch(
    batch: list[Paper],
    analyst: ClaudePaperAnalyst,
    *,
    run_date: date,
    scoring_config,
    feedback_context: dict | None = None,
) -> list:
    try:
        return analyst.score_papers(batch, run_date=run_date, scoring_config=scoring_config, feedback_context=feedback_context)
    except RuntimeError:
        if len(batch) == 1:
            raise
        midpoint = len(batch) // 2
        logger.warning("LLM scoring failed for batch of %s papers; retrying as %s and %s", len(batch), midpoint, len(batch) - midpoint)
        return [
            *_score_batch(
                batch[:midpoint],
                analyst,
                run_date=run_date,
                scoring_config=scoring_config,
                feedback_context=feedback_context,
            ),
            *_score_batch(
                batch[midpoint:],
                analyst,
                run_date=run_date,
                scoring_config=scoring_config,
                feedback_context=feedback_context,
            ),
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
    daily_listings: dict[str, ArxivDailyListing] = {}
    for category in arxiv_categories:
        try:
            daily_listings[category.category] = fetch_arxiv_daily_listing(category.category)
            logger.info(
                "arXiv daily listing: category=%s date=%s papers=%s available=%s",
                category.category,
                daily_listings[category.category].listing_date,
                len(daily_listings[category.category].paper_ids),
                daily_listings[category.category].available,
            )
        except Exception as exc:
            message = f"arXiv listing {category.category}: {exc}"
            logger.warning(message)
            errors.append(message)
    arxiv_cache_dir = settings.root_dir / settings.sources.arxiv.api_cache_dir if settings.sources.arxiv.api_cache_enabled else None
    arxiv_cache_ttl_seconds = settings.sources.arxiv.api_cache_ttl_hours * 3600
    for index, category in enumerate(arxiv_categories):
        if index and settings.sources.arxiv.api_request_delay_seconds > 0:
            time.sleep(settings.sources.arxiv.api_request_delay_seconds)
        try:
            papers.extend(
                fetch_arxiv_papers(
                    [category],
                    days_back=settings.sources.arxiv.days_back,
                    daily_listings=daily_listings,
                    retry_attempts=settings.sources.arxiv.api_retry_attempts,
                    retry_initial_delay_seconds=settings.sources.arxiv.api_retry_initial_delay_seconds,
                    retry_max_delay_seconds=settings.sources.arxiv.api_retry_max_delay_seconds,
                    cache_dir=arxiv_cache_dir,
                    cache_ttl_seconds=arxiv_cache_ttl_seconds,
                )
            )
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
