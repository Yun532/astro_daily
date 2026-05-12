from datetime import date, datetime, timezone

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
from astro_daily.models import Paper, PaperSummary, ScoreResult, WeekendLesson
from astro_daily.pipeline import DeferredRetryNeeded, evaluate_source_freshness, run_pipeline


def make_settings(tmp_path):
    return Settings(
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



def test_final_attempt_bypasses_primary_zero_defer(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    old_primary = make_paper("old-primary")
    wrote_report = False

    class FakeAnalyst:
        def __init__(self, *_args, **_kwargs):
            pass

        def score_papers(self, papers, **_kwargs):
            return []

        def summarize_papers(self, papers, **_kwargs):
            return []

    def fake_write_daily_report(**_kwargs):
        nonlocal wrote_report
        wrote_report = True
        path = tmp_path / "reports" / "2026-05-12.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# report\n", encoding="utf-8")
        return path

    monkeypatch.setattr("astro_daily.pipeline.load_settings", lambda _path: settings)
    monkeypatch.setattr("astro_daily.pipeline.fetch_all_sources", lambda _settings: ([old_primary], []))
    monkeypatch.setattr("astro_daily.pipeline.ClaudePaperAnalyst", FakeAnalyst)
    monkeypatch.setattr("astro_daily.pipeline.write_daily_report", fake_write_daily_report)
    monkeypatch.setattr("astro_daily.pipeline.attach_extracted_figures", lambda *_args, **_kwargs: type("Result", (), {"attempted": 0, "extracted": 0, "failed": 0})())
    monkeypatch.setattr("astro_daily.pipeline.generate_html_report", lambda _path: str(tmp_path / "docs" / "reports" / "2026-05-12.html"))
    monkeypatch.setattr("astro_daily.pipeline.ensure_html_latex_formulas_valid", lambda _path: FormulaIntegrityResult(checked_sections=1))

    result = run_pipeline(
        config_path="unused.yaml",
        run_date=date(2026, 5, 12),
        defer_if_unfresh=True,
        final_attempt=True,
        ignore_seen=True,
    )

    assert wrote_report
    assert result.kept_count == 0



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



def test_weekday_fallback_recommends_supplemental_papers_when_no_regular_papers_pass(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
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


def test_weekday_fallback_does_not_trigger_without_today_updates(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
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
