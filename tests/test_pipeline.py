from datetime import date, datetime, timezone

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
from astro_daily.models import Paper, PaperSummary, ScoreResult, WeekendLesson
from astro_daily.pipeline import run_pipeline


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
