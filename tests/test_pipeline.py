from datetime import date, datetime, timezone
import json
import threading

import pytest

from astro_daily.config import (
    ArxivCategoryConfig,
    ArxivConfig,
    ClawBotConfig,
    LlmConfig,
    PublishConfig,
    ReportConfig,
    RssConfig,
    ScoringConfig,
    Settings,
    SourcesConfig,
    WechatConfig,
)
from astro_daily.formula_integrity import FormulaIntegrityResult
from astro_daily.models import ExtractedFigure, FigureSelection, Paper, PaperScore, PaperSummary, ScoredPaper, ScoreResult, WeekendLesson
from astro_daily.pipeline import DeferredRetryNeeded, _select_figures_for_items_parallel, evaluate_source_freshness, fetch_all_sources, run_pipeline
from astro_daily.seen import SeenStore
from astro_daily.sources.arxiv import ArxivDailyListing


def make_settings(tmp_path):
    settings = Settings(
        sources=SourcesConfig(
            arxiv=ArxivConfig(primary=[ArxivCategoryConfig(category="astro-ph.HE")]),
            rss=RssConfig(),
        ),
        scoring=ScoringConfig(),
        llm=LlmConfig(),
        report=ReportConfig(output_dir="reports", seen_file="seen.json"),
        wechat=WechatConfig(enabled=False),
        clawbot=ClawBotConfig(enabled=False),
        publish=PublishConfig(enabled=False),
        anthropic_api_key="test-token",
        root_dir=tmp_path,
    )
    settings.sources.arxiv.on_demand_backfill_with_category_search = False
    return settings


def make_paper(paper_id="old"):
    return Paper(
        paper_id=paper_id,
        title="Old high-energy paper",
        url=f"https://example.com/{paper_id}",
        source="arXiv",
        category="astro-ph.HE",
        published=datetime(2026, 5, 1, tzinfo=timezone.utc),
        source_batch_date=date(2026, 5, 1),
    )


def make_lesson(title="经典 GRB 余辉课程", anchor="Blandford-McKee self-similar blast wave"):
    return WeekendLesson(
        topic="GRB afterglow",
        title_cn=title,
        anchor_work_cn=anchor,
        why_classic_cn="解释相对论激波余辉的经典框架。",
        detailed_explanation_cn="详细讲解。",
        background_cn="背景。",
        basic_theory_cn="基础理论。",
        formula_derivation_cn="$E\\sim\\Gamma^2Mc^2$。",
        model_fitting_cn="拟合。",
        key_sections_cn="重点章节。",
        figures_to_check_cn="重点图。",
        key_figure_analysis_cn="图 1 读法。",
        followup_reading_cn="后续阅读。",
        search_keywords=["GRB afterglow", "Blandford McKee"],
        links=[],
    )


def read_run_log(tmp_path):
    logs = sorted((tmp_path / "logs").glob("pipeline-*.jsonl"))
    assert logs
    return [json.loads(line) for line in logs[-1].read_text(encoding="utf-8").splitlines()]


def test_fetch_all_sources_uses_daily_listing_id_mode(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    listing = ArxivDailyListing("astro-ph.HE", date(2026, 5, 12), {"2605.00006"}, True)
    fetched_by_ids = []

    def fake_fetch_by_ids(category, paper_ids, **kwargs):
        fetched_by_ids.append((category, sorted(paper_ids), kwargs.get("source_batch_date")))
        return [make_paper("2605.00006").model_copy(update={"source_batch_date": kwargs.get("source_batch_date")})]

    monkeypatch.setattr("astro_daily.pipeline.fetch_arxiv_daily_listing", lambda *_args, **_kwargs: listing)
    monkeypatch.setattr("astro_daily.pipeline.fetch_arxiv_papers_by_ids", fake_fetch_by_ids)
    monkeypatch.setattr("astro_daily.pipeline.fetch_arxiv_papers", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("category search should not run")))

    papers, errors = fetch_all_sources(settings)

    assert not errors
    assert fetched_by_ids == [("astro-ph.HE", ["2605.00006"], date(2026, 5, 12))]
    assert papers[0].paper_id == "2605.00006"


def test_daily_listing_metadata_partial_failure_keeps_other_categories(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    settings.sources.arxiv.secondary = [ArxivCategoryConfig(category="astro-ph.IM")]
    listings = {
        "astro-ph.HE": ArxivDailyListing("astro-ph.HE", date(2026, 5, 12), {"2605.00006"}, True),
        "astro-ph.IM": ArxivDailyListing("astro-ph.IM", date(2026, 5, 12), {"2605.00007"}, True),
    }

    def fake_fetch_by_ids(category, paper_ids, **kwargs):
        if category == "astro-ph.HE":
            raise TimeoutError("metadata timeout")
        paper_id = sorted(paper_ids)[0]
        return [make_paper(paper_id).model_copy(update={"category": category, "source_batch_date": kwargs.get("source_batch_date")})]

    monkeypatch.setattr("astro_daily.pipeline.fetch_arxiv_daily_listing", lambda category, **_kwargs: listings[category])
    monkeypatch.setattr("astro_daily.pipeline.fetch_arxiv_papers_by_ids", fake_fetch_by_ids)
    monkeypatch.setattr("astro_daily.pipeline.fetch_arxiv_papers", lambda *_args, **_kwargs: [])

    papers, errors = fetch_all_sources(settings)

    assert [paper.paper_id for paper in papers] == ["2605.00007"]
    assert any("astro-ph.HE chunk 1" in error for error in errors)


def test_daily_listing_metadata_fallback_filters_to_listing_ids(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    listing = ArxivDailyListing("astro-ph.HE", date(2026, 5, 12), {"2605.00006"}, True)
    listing_paper = make_paper("2605.00006").model_copy(update={"source_batch_date": date(2026, 5, 12)})
    old_search_paper = make_paper("2605.99999").model_copy(update={"source_batch_date": None})

    monkeypatch.setattr("astro_daily.pipeline.fetch_arxiv_daily_listing", lambda *_args, **_kwargs: listing)
    monkeypatch.setattr("astro_daily.pipeline.fetch_arxiv_papers_by_ids", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("id_list timeout")))
    monkeypatch.setattr("astro_daily.pipeline.fetch_arxiv_papers", lambda *_args, **_kwargs: [listing_paper, old_search_paper])

    papers, errors = fetch_all_sources(settings)

    assert [paper.paper_id for paper in papers] == ["2605.00006"]
    assert papers[0].source_batch_date == date(2026, 5, 12)
    assert any("id_list timeout" in error for error in errors)


def test_weekday_fetches_on_demand_backfill_when_selection_is_sparse(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    settings.sources.arxiv.on_demand_backfill_with_category_search = True
    settings.scoring.same_day_target = 2
    today = make_paper("today").model_copy(
        update={
            "title": "Today sparse paper",
            "source_batch_date": date(2026, 5, 12),
        }
    )
    old = make_paper("old-backfill").model_copy(
        update={
            "title": "Valuable older paper",
            "source_batch_date": None,
            "published": datetime(2026, 5, 10, tzinfo=timezone.utc),
        }
    )
    backfill_called = False

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, papers, **_kwargs):
            return [
                ScoreResult(
                    paper_id=paper.paper_id,
                    novelty_score=8,
                    importance_score=8,
                    relevance_to_me=8,
                    final_score=8,
                    keep=True,
                    reason="good candidate",
                )
                for paper in papers
            ]

        def summarize_papers(self, papers, **_kwargs):
            return [
                PaperSummary(
                    paper_id=paper.paper_id,
                    title_cn=f"中文 {paper.paper_id}",
                    summary_cn="摘要",
                    why_important_cn="重要",
                    value_cn="价值",
                    why_care_cn="值得关注",
                )
                for paper in papers
            ]

    def fake_backfill(_settings):
        nonlocal backfill_called
        backfill_called = True
        return [old], []

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([today], []))
    monkeypatch.setattr("astro_daily.pipeline._fetch_arxiv_category_search_sources", fake_backfill)
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.attach_extracted_figures", lambda *_args, **_kwargs: type("Result", (), {"attempted": 0, "extracted": 0, "failed": 0})())
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", lambda path: str(tmp_path / "docs" / "reports" / "2026-05-12.html"))
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", lambda _path: FormulaIntegrityResult(checked_sections=1))

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 12), dry_run=False)

    assert backfill_called
    assert result.kept_count == 2


def test_weekday_run_scores_candidates_in_batches(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    settings.scoring.max_candidates = 45
    papers = [make_paper(f"2605.{index:05d}").model_copy(update={"title": f"High-energy paper {index}"}) for index in range(45)]
    batch_sizes = []

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, papers, **_kwargs):
            batch_sizes.append(len(papers))
            return [
                ScoreResult(
                    paper_id=paper.paper_id,
                    novelty_score=8,
                    importance_score=8,
                    relevance_to_me=8,
                    final_score=8,
                    keep=True,
                    reason="important",
                )
                for paper in papers
            ]

        def summarize_papers(self, papers, **_kwargs):
            return [
                PaperSummary(
                    paper_id=paper.paper_id,
                    title_cn="标题",
                    summary_cn="总结",
                    why_important_cn="重要",
                    value_cn="价值",
                    why_care_cn="关注",
                )
                for paper in papers
            ]

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: (papers, []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.attach_extracted_figures", lambda *_args, **_kwargs: type("Result", (), {"attempted": 0, "extracted": 0, "failed": 0})())

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 1), dry_run=False, ignore_seen=True)

    assert batch_sizes == [20, 20, 5]
    assert result.kept_count == settings.scoring.max_papers_per_report



def test_successful_run_writes_stage_log_with_threshold_count(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    paper = make_paper("2605.10001").model_copy(update={"source_batch_date": date(2026, 5, 12), "title": "Logged threshold paper"})

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, papers, **_kwargs):
            return [
                ScoreResult(
                    paper_id=paper.paper_id,
                    novelty_score=8,
                    importance_score=8,
                    relevance_to_me=8,
                    final_score=8,
                    keep=True,
                    reason="important",
                )
                for paper in papers
            ]

        def summarize_papers(self, papers, **_kwargs):
            return [
                PaperSummary(
                    paper_id=paper.paper_id,
                    title_cn="标题",
                    summary_cn="总结",
                    why_important_cn="重要",
                    value_cn="价值",
                    why_care_cn="关注",
                )
                for paper in papers
            ]

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([paper], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", lambda path: str(tmp_path / "docs" / "reports" / "2026-05-12.html"))
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", lambda _path: FormulaIntegrityResult(checked_sections=1))

    run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 12), dry_run=True, ignore_seen=True)

    records = read_run_log(tmp_path)
    apply_end = next(record for record in records if record["stage"] == "apply_policy" and record["event"] == "end")
    assert apply_end["data"]["regular_threshold_passing_count"] == 1
    assert apply_end["data"]["selected_papers"][0]["title"] == "Logged threshold paper"
    assert apply_end["data"]["selected_papers"][0]["source_batch_date"] == "2026-05-12"
    assert any(record["stage"] == "fetch_sources" and record["event"] == "end" for record in records)
    assert any(record["stage"] == "seen_update" and record["event"] == "end" and record["data"]["updated"] is False for record in records)



def test_report_generation_failure_writes_error_stage_log(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    paper = make_paper("2605.10002").model_copy(update={"source_batch_date": date(2026, 5, 12)})

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, papers, **_kwargs):
            return [
                ScoreResult(
                    paper_id=paper.paper_id,
                    novelty_score=8,
                    importance_score=8,
                    relevance_to_me=8,
                    final_score=8,
                    keep=True,
                    reason="important",
                )
                for paper in papers
            ]

        def summarize_papers(self, papers, **_kwargs):
            return [
                PaperSummary(
                    paper_id=paper.paper_id,
                    title_cn="鏍囬",
                    summary_cn="鎬荤粨",
                    why_important_cn="閲嶈",
                    value_cn="浠峰€?",
                    why_care_cn="鍏虫敞",
                )
                for paper in papers
            ]

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([paper], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.write_daily_report", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("report write broke")))

    with pytest.raises(RuntimeError, match="report write broke"):
        run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 12), dry_run=True, ignore_seen=True)

    records = read_run_log(tmp_path)
    error = next(record for record in records if record["stage"] == "write_markdown_report" and record["event"] == "error")
    assert error["data"]["error_type"] == "RuntimeError"
    assert error["data"]["error_message"] == "report write broke"


def test_single_summary_failure_uses_fallback_and_continues(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    paper = make_paper("2605.10004").model_copy(update={"source_batch_date": date(2026, 5, 12), "abstract": "A relevant high-energy abstract."})

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, papers, **_kwargs):
            return [
                ScoreResult(
                    paper_id=paper.paper_id,
                    novelty_score=8,
                    importance_score=8,
                    relevance_to_me=8,
                    final_score=8,
                    keep=True,
                    reason="important",
                )
                for paper in papers
            ]

        def summarize_papers(self, *_args, **_kwargs):
            raise RuntimeError("summary json broke")

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([paper], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", lambda path: str(tmp_path / "docs" / "reports" / "2026-05-12.html"))
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", lambda _path: FormulaIntegrityResult(checked_sections=1))

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 12), dry_run=True, ignore_seen=True)

    assert result.kept_count == 1
    report = (tmp_path / "reports" / "2026-05-12.md").read_text(encoding="utf-8")
    assert "自动详细解读生成失败" in report
    records = read_run_log(tmp_path)
    summary_end = next(record for record in records if record["stage"] == "summaries_and_figures" and record["event"] == "end")
    assert summary_end["data"]["summary_count"] == 1



def test_parallel_figure_extraction_starts_before_summary(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    settings.figure_extraction.enabled = True
    paper = make_paper("2605.10003").model_copy(update={"source_batch_date": date(2026, 5, 12)})
    extraction_started = False

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, papers, **_kwargs):
            return [
                ScoreResult(
                    paper_id=paper.paper_id,
                    novelty_score=8,
                    importance_score=8,
                    relevance_to_me=8,
                    final_score=8,
                    keep=True,
                    reason="important",
                )
                for paper in papers
            ]

        def summarize_papers(self, papers, **_kwargs):
            assert extraction_started
            return [
                PaperSummary(
                    paper_id=paper.paper_id,
                    title_cn="标题",
                    summary_cn="总结",
                    why_important_cn="重要",
                    value_cn="价值",
                    why_care_cn="关注",
                )
                for paper in papers
            ]

        def select_figures_for_paper(self, **_kwargs):
            return []

    def fake_extract(*_args, **_kwargs):
        nonlocal extraction_started
        extraction_started = True
        return []

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([paper], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.extract_figures_for_item", fake_extract)
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", lambda path: str(tmp_path / "docs" / "reports" / "2026-05-12.html"))
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", lambda _path: FormulaIntegrityResult(checked_sections=1))

    run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 12), dry_run=True, ignore_seen=True)

    records = read_run_log(tmp_path)
    summary_end = next(record for record in records if record["stage"] == "summaries_and_figures" and record["event"] == "end")
    assert summary_end["data"]["figure_attempted"] == 1



def test_figure_selection_runs_in_parallel(tmp_path):
    settings = make_settings(tmp_path)
    settings.figure_extraction.parallel_workers = 2
    barrier = threading.Barrier(2)
    passed_barrier = 0
    lock = threading.Lock()

    def item_with_figure(paper_id):
        paper = make_paper(paper_id)
        return (
            ScoredPaper(
                paper=paper,
                score=PaperScore(novelty_score=8, importance_score=8, relevance_to_me=8, final_score=8, keep=True, reason="important"),
                summary=PaperSummary(
                    paper_id=paper_id,
                    title_cn="标题",
                    summary_cn="总结",
                    why_important_cn="重要",
                    value_cn="价值",
                    why_care_cn="关注",
                ),
            ),
            [ExtractedFigure(fig_id="Fig01", image_url="../assets/Fig01.png", caption="caption")],
        )

    class FakeAnalyst:
        def select_figures_for_paper(self, **_kwargs):
            nonlocal passed_barrier
            barrier.wait(timeout=2)
            with lock:
                passed_barrier += 1
            return [FigureSelection(fig_id="Fig01", relevance_score=9, related_section_cn="图解读", reason_cn="匹配")]

    extracted = _select_figures_for_items_parallel(
        [item_with_figure("2605.10005"), item_with_figure("2605.10006")],
        settings,
        FakeAnalyst(),
        run_date=date(2026, 5, 12),
    )

    assert extracted == 2
    assert passed_barrier == 2



def test_weekend_run_scores_no_candidates(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    score_called = False

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, *_args, **_kwargs):
            nonlocal score_called
            score_called = True
            return []

        def generate_weekend_lessons(self, **_kwargs):
            return [make_lesson()]

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([make_paper()], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 3), dry_run=False)

    assert result.kept_count == 0
    assert result.classic_lesson_count == 1
    assert result.classic_paper_count == 0
    assert not score_called


def test_clawbot_failure_does_not_prevent_seen_update(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    settings.clawbot.enabled = True
    settings.clawbot.send_report = True
    settings.clawbot.default_recipient = "user@im.wechat"

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate_weekend_lessons(self, **_kwargs):
            return [make_lesson()]

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.send_clawbot_report_message", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ret -2")))

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 3), dry_run=False)

    assert result.classic_lesson_count == 1
    from astro_daily.seen import SeenStore

    records = SeenStore.load(settings.seen_path).records
    assert "lesson:title:经典 grb 余辉课程" in records


def test_successful_weekend_run_records_lesson_and_passes_history(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    previous = make_lesson(title="已经讲过的 GRB 课程", anchor="old anchor work")
    from astro_daily.seen import SeenStore

    store = SeenStore.load(settings.seen_path)
    store.mark_lessons([previous], seen_date=date(2026, 5, 2))
    store.save()
    captured_avoid = []

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate_weekend_lessons(self, **kwargs):
            nonlocal captured_avoid
            captured_avoid = kwargs["avoid_previous_lessons"]
            return [make_lesson(title="新的 IACT 课程", anchor="H.E.S.S. Galactic Center observations")]

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 3), dry_run=False)

    assert result.classic_lesson_count == 1
    assert captured_avoid == [
        {
            "title": "已经讲过的 GRB 课程",
            "topic": "GRB afterglow",
            "anchor_work": "old anchor work",
        }
    ]
    records = SeenStore.load(settings.seen_path).records
    assert "lesson:title:新的 iact 课程" in records
    assert "lesson:anchor:h.e.s.s. galactic center observations" in records


def test_weekend_run_uses_planned_syllabus_lesson(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    (tmp_path / "weekend_syllabus.yaml").write_text(
        """
lessons:
  - id: tde-01
    series_id: tde-beginner
    series_title_cn: TDE 从零到前沿课程
    part_index: 1
    planned_parts: 2
    title_cn: TDE 第一讲
    topic: tidal disruption basics
    anchor_work_cn: Rees 1988
    prerequisites_cn: [零基础]
    lesson_scope_cn: 潮汐半径和 fallback
    why_classic_cn: 建立 TDE 基本框架
    classic_paper_ids: [rees-1988-tde]
    modern_directions_cn: [partial disruption]
    search_keywords: [tidal disruption event fallback]
    links: [https://ui.adsabs.harvard.edu/abs/1988Natur.333..523R/abstract]
""",
        encoding="utf-8",
    )
    captured = {}

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate_weekend_lessons(self, **kwargs):
            captured.update(kwargs)
            planned = kwargs["planned_weekend_lesson"]
            return [
                make_lesson(
                    title=planned["title_cn"],
                    anchor=planned["anchor_work_cn"],
                ).model_copy(
                    update={
                        "series_id": planned["series_id"],
                        "series_title_cn": planned["series_title_cn"],
                        "part_index": planned["part_index"],
                        "planned_parts": planned["planned_parts"],
                    }
                )
            ]

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 3), dry_run=True)

    assert result.classic_lesson_count == 1
    assert captured["planned_weekend_lesson"]["id"] == "tde-01"
    assert "STRICT_WEEKEND_SYLLABUS_LESSON" in captured["topics"][0]
    assert "TDE 第一讲" in captured["topics"][0]


def test_formula_check_runs_before_html_generation(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    calls = []

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate_weekend_lessons(self, **_kwargs):
            return [make_lesson()]

    def fake_write_daily_report(**_kwargs):
        calls.append("write")
        path = tmp_path / "reports" / "2026-05-03.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# report\n", encoding="utf-8")
        return path

    def fake_repair_report_latex_formulas(_path):
        calls.append("repair")
        return FormulaIntegrityResult(checked_sections=1)

    def fake_generate_html_report(_path):
        calls.append("html")
        return str(tmp_path / "docs" / "reports" / "2026-05-03.html")

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.write_daily_report", fake_write_daily_report)
    def fake_ensure_html_latex_formulas_valid(_path):
        calls.append("validate")
        return FormulaIntegrityResult(checked_sections=1)

    monkeypatch.setattr("astro_daily.pipeline.repair_report_latex_formulas", fake_repair_report_latex_formulas)
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", fake_generate_html_report)
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", fake_ensure_html_latex_formulas_valid)

    run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 3), dry_run=False)

    assert calls[:4] == ["write", "repair", "html", "validate"]


def test_formula_check_failure_does_not_block_html_generation(monkeypatch, tmp_path, caplog):
    settings = make_settings(tmp_path)
    html_called = False

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate_weekend_lessons(self, **_kwargs):
            return [make_lesson()]

    def fake_write_daily_report(**_kwargs):
        path = tmp_path / "reports" / "2026-05-03.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# report\n", encoding="utf-8")
        return path

    def fake_generate_html_report(_path):
        nonlocal html_called
        html_called = True
        return str(tmp_path / "docs" / "reports" / "2026-05-03.html")

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.write_daily_report", fake_write_daily_report)
    monkeypatch.setattr("astro_daily.pipeline.repair_report_latex_formulas", lambda _path: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", fake_generate_html_report)
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", lambda _path: FormulaIntegrityResult(checked_sections=1))

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 3), dry_run=False)

    assert html_called
    assert result.classic_lesson_count == 1
    assert "Formula integrity check failed" in caplog.text


def test_html_formula_validation_failure_blocks_publish(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    publish_called = False

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate_weekend_lessons(self, **_kwargs):
            return [make_lesson()]

    def fake_write_daily_report(**_kwargs):
        path = tmp_path / "reports" / "2026-05-03.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# report\n", encoding="utf-8")
        return path

    def fake_publish(*_args, **_kwargs):
        nonlocal publish_called
        publish_called = True
        raise AssertionError("publish should not run")

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.write_daily_report", fake_write_daily_report)
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", lambda _path: str(tmp_path / "docs" / "reports" / "2026-05-03.html"))
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", lambda _path: (_ for _ in ()).throw(RuntimeError("bad html formula")))
    monkeypatch.setattr("astro_daily.pipeline.publish_report_if_enabled", fake_publish)

    with pytest.raises(RuntimeError, match="bad html formula"):
        run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 3), dry_run=False)

    assert not publish_called



def test_defers_on_temporary_primary_arxiv_error_before_report_generation(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    wrote_report = False

    def fake_write_daily_report(**_kwargs):
        nonlocal wrote_report
        wrote_report = True
        raise AssertionError("report should not be written when freshness defers")

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([], ["arXiv astro-ph.HE: 429 Client Error"]))
    monkeypatch.setattr("astro_daily.pipeline.write_daily_report", fake_write_daily_report)

    with pytest.raises(DeferredRetryNeeded, match="temporary primary arXiv"):
        run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 12), defer_if_unfresh=True)

    assert not wrote_report



def test_defers_when_weekday_primary_arxiv_has_no_today_papers(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    old_primary = make_paper("old-primary")

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([old_primary], []))

    with pytest.raises(DeferredRetryNeeded, match="daily listing"):
        run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 12), defer_if_unfresh=True)



def test_final_attempt_still_defers_when_weekday_primary_batch_unconfirmed(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    old_primary = make_paper("old-primary")
    wrote_report = False

    def fake_write_daily_report(**_kwargs):
        nonlocal wrote_report
        wrote_report = True
        raise AssertionError("report should not be written when primary batch is unconfirmed")

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([old_primary], []))
    monkeypatch.setattr("astro_daily.pipeline.write_daily_report", fake_write_daily_report)

    with pytest.raises(DeferredRetryNeeded, match="daily listing"):
        run_pipeline(
            config_path="unused.yaml",
            run_date=date(2026, 5, 12),
            defer_if_unfresh=True,
            final_attempt=True,
            ignore_seen=True,
        )

    assert not wrote_report


def test_final_attempt_still_defers_on_temporary_primary_error(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([], ["arXiv astro-ph.HE: 429 Client Error"]))

    with pytest.raises(DeferredRetryNeeded, match="temporary primary arXiv"):
        run_pipeline(
            config_path="unused.yaml",
            run_date=date(2026, 5, 12),
            defer_if_unfresh=True,
            final_attempt=True,
        )



def test_weekend_does_not_defer_on_primary_zero(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate_weekend_lessons(self, **_kwargs):
            return [make_lesson()]

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 17), defer_if_unfresh=True)

    assert result.classic_lesson_count == 1



def test_source_freshness_counts_primary_batch_today_before_seen_filter(tmp_path):
    settings = make_settings(tmp_path)
    today_primary = make_paper("today-primary").model_copy(
        update={
            "published": datetime(2026, 5, 11, tzinfo=timezone.utc),
            "updated": datetime(2026, 5, 11, tzinfo=timezone.utc),
            "source_batch_date": date(2026, 5, 12),
        }
    )

    decision = evaluate_source_freshness(settings=settings, papers=[today_primary], source_errors=[], run_date=date(2026, 5, 12))

    assert decision.primary_today_count == 1
    assert decision.primary_batch_confirmed
    assert not decision.should_defer



def test_source_freshness_ignores_rss_today_for_primary_arxiv(tmp_path):
    settings = make_settings(tmp_path)
    rss_today = Paper(
        paper_id="rss-today",
        title="Journal paper",
        url="https://example.com/rss",
        source="Nature",
        published=datetime(2026, 5, 12, tzinfo=timezone.utc),
    )

    decision = evaluate_source_freshness(settings=settings, papers=[rss_today], source_errors=[], run_date=date(2026, 5, 12))

    assert decision.primary_today_count == 0
    assert decision.should_defer


def test_source_freshness_does_not_defer_when_primary_batch_confirmed_with_warning(tmp_path):
    settings = make_settings(tmp_path)
    today_primary = make_paper("today-primary").model_copy(update={"source_batch_date": date(2026, 5, 12)})

    decision = evaluate_source_freshness(
        settings=settings,
        papers=[today_primary],
        source_errors=["arXiv daily metadata astro-ph.HE chunk 2: Read timed out."],
        run_date=date(2026, 5, 12),
    )

    assert decision.primary_batch_confirmed
    assert not decision.should_defer



def test_weekday_fallback_recommends_supplemental_papers_when_no_regular_papers_pass(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    settings.sources.arxiv.on_demand_backfill_with_category_search = False
    settings.scoring.supplemental_max_candidates = 10
    today = Paper(
        paper_id="today",
        title="Published today but below threshold",
        url="https://example.com/today",
        source="RSS",
        category="astro-ph.CO",
        published=datetime(2026, 5, 8, tzinfo=timezone.utc),
    )
    old_papers = [
        Paper(
            paper_id=f"old-{index}",
            title=f"Supplemental paper {index}",
            url=f"https://example.com/old-{index}",
            source="arXiv",
            category="astro-ph.CO",
            published=datetime(2026, 5, 7 - index, tzinfo=timezone.utc),
        )
        for index in range(4)
    ]

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, papers, **_kwargs):
            return [
                ScoreResult(
                    paper_id=paper.paper_id,
                    novelty_score=7,
                    importance_score=7,
                    relevance_to_me=7,
                    final_score=7,
                    keep=True,
                    reason="高质量补读候选",
                )
                for paper in papers
            ]

        def summarize_papers(self, papers, **_kwargs):
            return [
                PaperSummary(
                    paper_id=paper.paper_id,
                    title_cn=f"中文 {paper.paper_id}",
                    summary_cn="补读摘要",
                    why_important_cn="补读重要性",
                    value_cn="补读价值",
                    why_care_cn="值得补读",
                )
                for paper in papers
            ]

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([today, *old_papers], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.attach_extracted_figures", lambda *_args, **_kwargs: type("Result", (), {"attempted": 0, "extracted": 0, "failed": 0})())
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", lambda path: str(tmp_path / "docs" / "reports" / "2026-05-08.html"))
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", lambda _path: FormulaIntegrityResult(checked_sections=1))

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 8), dry_run=False)

    assert result.kept_count == 0
    assert result.supplemental_count == 3
    assert "补充推荐：3 篇" in result.wechat_message
    assert "今日精选" not in result.wechat_message
    report = (tmp_path / "reports" / "2026-05-08.md").read_text(encoding="utf-8")
    assert "补充推荐：近期/较早未读论文（非今日论文）" in report
    assert "Published today but below threshold" not in report

    from astro_daily.seen import SeenStore

    records = SeenStore.load(settings.seen_path).records
    assert "old-0" in records
    assert "old-1" in records
    assert "old-2" in records
    assert "today" not in records


def test_weekday_fallback_adds_classic_paper_when_content_floor_is_not_met(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    settings.scoring.daily_content_floor = 3
    settings.sources.arxiv.on_demand_backfill_with_category_search = False
    (tmp_path / "classic_papers.yaml").write_text(
        """
- id: li-ma
  title: Analysis methods for results in gamma-ray astronomy
  authors: [T.-P. Li, Y.-Q. Ma]
  year: 1983
  url: https://ui.adsabs.harvard.edu/abs/1983ApJ...272..317L/abstract
  topic: Gamma-ray astronomy statistics
  tags: [IACT, significance]
  why_classic_cn: Li-Ma 显著性公式是伽马射线天文 on/off 计数分析的标准工具。
""",
        encoding="utf-8",
    )
    today = make_paper("today-classic-trigger").model_copy(update={"source_batch_date": date(2026, 5, 12)})

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, papers, **_kwargs):
            return [
                ScoreResult(
                    paper_id=paper.paper_id,
                    novelty_score=8,
                    importance_score=8,
                    relevance_to_me=8,
                    final_score=8,
                    keep=True,
                    reason="good new paper",
                )
                for paper in papers
            ]

        def summarize_papers(self, papers, **_kwargs):
            return [
                PaperSummary(
                    paper_id=paper.paper_id,
                    title_cn=f"中文 {paper.paper_id}",
                    summary_cn="这是一段足够清楚的摘要，说明科学问题、方法和结论。" * 3,
                    why_important_cn="这篇文章或经典旧文重要，因为它支撑后续高能天体物理分析。" * 3,
                    value_cn="它提供了理论、观测或统计方法价值。" * 4,
                    why_care_cn="它值得关注，因为后续很多论文会复用这个框架。" * 4,
                    detailed_explanation_cn="详细讲解科学问题、方法、关键结果和局限。" * 8,
                    background_cn="背景知识。" * 40,
                    basic_theory_cn="基础理论。" * 40,
                    formula_derivation_cn=" ".join(["$$E=mc^2$$", "\\(R=ct\\)", "\\[F=L/(4\\pi D^2)\\]", "\\(N=A E^{-p}\\)", "$$\\tau=n\\sigma R$$"]) + " 推导。",
                    model_fitting_cn="模型拟合和残差诊断。" * 20,
                    key_sections_cn="重点章节阅读路径。" * 20,
                    figures_to_check_cn="重点图表。" * 40,
                    key_figure_analysis_cn="图 1 看坐标轴和模型线。" * 20,
                    related_work_cn="相关工作。" * 40,
                )
                for paper in papers
            ]

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([today], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", lambda path: str(tmp_path / "docs" / "reports" / "2026-05-12.html"))
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", lambda _path: FormulaIntegrityResult(checked_sections=1))

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 12), dry_run=False)

    assert result.kept_count == 1
    assert result.classic_paper_count == 1
    assert "经典旧文精读：1 篇" in result.wechat_message
    report = (tmp_path / "reports" / "2026-05-12.md").read_text(encoding="utf-8")
    assert "经典旧文精读：具体经典论文 / 重要旧文" in report
    records = SeenStore.load(settings.seen_path).records
    assert "classic:li-ma" in records


def test_summary_quality_repair_updates_thin_sections(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    paper = make_paper("repair-me").model_copy(update={"source_batch_date": date(2026, 5, 12)})
    repaired_fields = []

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, papers, **_kwargs):
            return [
                ScoreResult(
                    paper_id=paper.paper_id,
                    novelty_score=8,
                    importance_score=8,
                    relevance_to_me=8,
                    final_score=8,
                    keep=True,
                    reason="important",
                )
                for paper in papers
            ]

        def summarize_papers(self, papers, **_kwargs):
            return [
                PaperSummary(
                    paper_id=paper.paper_id,
                    title_cn="薄摘要",
                    summary_cn="short",
                    why_important_cn="short",
                    value_cn="short",
                    why_care_cn="short",
                )
                for paper in papers
            ]

        def repair_paper_summary(self, **kwargs):
            repaired_fields.extend(kwargs["requested_fields"])
            long = "修复后章节包含具体科学问题、方法、结果、限制和阅读指引。" * 20
            formulas = " ".join(["$$E=mc^2$$", "\\(R=ct\\)", "\\[F=L/(4\\pi D^2)\\]", "\\(N=A E^{-p}\\)", "$$\\tau=n\\sigma R$$"])
            return {
                field: (long + formulas if field == "formula_derivation_cn" else long)
                for field in kwargs["requested_fields"]
            }

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([paper], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", lambda path: str(tmp_path / "docs" / "reports" / "2026-05-12.html"))
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", lambda _path: FormulaIntegrityResult(checked_sections=1))

    run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 12), dry_run=True, ignore_seen=True)

    assert "formula_derivation_cn" in repaired_fields
    report = (tmp_path / "reports" / "2026-05-12.md").read_text(encoding="utf-8")
    assert "修复后章节" in report
    summary_end = next(record for record in read_run_log(tmp_path) if record["stage"] == "summaries_and_figures" and record["event"] == "end")
    assert summary_end["data"]["repaired_summary_count"] == 1


def test_weekday_fallback_does_not_trigger_without_today_updates(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    settings.sources.arxiv.on_demand_backfill_with_category_search = False
    old_paper = make_paper("old-only").model_copy(update={"category": "astro-ph.CO"})

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, papers, **_kwargs):
            return [
                ScoreResult(
                    paper_id=paper.paper_id,
                    novelty_score=7,
                    importance_score=7,
                    relevance_to_me=7,
                    final_score=7,
                    keep=True,
                    reason="below regular threshold",
                )
                for paper in papers
            ]

        def summarize_papers(self, papers, **_kwargs):
            return []

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([old_paper], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.attach_extracted_figures", lambda *_args, **_kwargs: type("Result", (), {"attempted": 0, "extracted": 0, "failed": 0})())
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", lambda path: str(tmp_path / "docs" / "reports" / "2026-05-08.html"))
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", lambda _path: FormulaIntegrityResult(checked_sections=1))

    result = run_pipeline(config_path="unused.yaml", run_date=date(2026, 5, 8), dry_run=False)

    assert result.kept_count == 0
    assert result.supplemental_count == 0
    assert "补充推荐" not in result.wechat_message
