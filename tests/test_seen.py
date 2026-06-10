from datetime import date

from astro_daily.models import Paper, WeekendLesson
from astro_daily.seen import SeenStore, deduplicate_papers


def paper(paper_id: str, title: str = "Title", *, source: str = "test", url: str | None = None) -> Paper:
    return Paper(paper_id=paper_id, title=title, url=url or f"https://example.com/{paper_id}", source=source)


def lesson(title: str = "经典课程", anchor: str = "classic anchor") -> WeekendLesson:
    return WeekendLesson(
        topic="GRB afterglow",
        title_cn=title,
        anchor_work_cn=anchor,
        series_id="grb-afterglow",
        series_title_cn="GRB afterglow course",
        part_index=1,
        planned_parts=3,
        lesson_scope_cn="Blast-wave dynamics",
        previous_context_cn="First part of the series",
        why_classic_cn="经典原因。",
        detailed_explanation_cn="详细解释。",
        background_cn="背景。",
        basic_theory_cn="理论。",
        formula_derivation_cn="$E=mc^2$。",
        model_fitting_cn="拟合。",
        key_sections_cn="章节。",
        figures_to_check_cn="图表。",
        key_figure_analysis_cn="图 1。",
        followup_reading_cn="阅读。",
    )


def test_missing_seen_file_is_empty(tmp_path):
    store = SeenStore.load(tmp_path / "seen.json")
    assert not store.is_seen(paper("1"))


def test_mark_and_reload_seen_file(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore.load(path)
    item = paper("1")
    store.mark_many([item], seen_date=date(2026, 5, 2))
    store.save()
    loaded = SeenStore.load(path)
    assert loaded.is_seen(item)


def test_deduplicate_by_title():
    first = paper("1", "Same Title")
    second = paper("2", " same   title ")
    assert deduplicate_papers([first, second]) == [first]


def test_deduplicate_prefers_prestige_journal_version_over_arxiv():
    arxiv = paper(
        "2605.00001",
        "Instantaneous jet power measured in an accreting black hole",
        source="arXiv",
        url="https://arxiv.org/abs/2605.00001",
    )
    nature = paper(
        "rss:10.1038/s41550-026-02829-2",
        "Instantaneous jet power measured in an accreting black hole",
        source="Nature Astronomy",
        url="https://www.nature.com/articles/s41550-026-02829-2",
    )

    assert deduplicate_papers([arxiv, nature]) == [nature]


def test_deduplicate_matches_loose_title_variants():
    arxiv = paper(
        "2605.00002",
        "LHAASO J1849-0002: A Hybrid Lepto-Hadronic Interpretation of PeV Gamma-Ray Emission",
        source="arXiv",
    )
    nature = paper(
        "rss:nature",
        "LHAASO J1849 0002 -- a hybrid lepto hadronic interpretation of PeV gamma ray emission",
        source="Nature",
    )

    assert deduplicate_papers([arxiv, nature]) == [nature]


def test_seen_matches_loose_title_variant_after_marking(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore.load(path)
    store.mark_many(
        [
            paper(
                "2605.00003",
                "Charge-dependent spectral softenings of primary cosmic rays below the knee",
                source="arXiv",
            )
        ],
        seen_date=date(2026, 5, 2),
    )
    store.save()

    loaded = SeenStore.load(path)

    assert loaded.is_seen(
        paper(
            "rss:nature",
            "Charge dependent spectral softenings of primary cosmic-rays below the knee",
            source="Nature",
        )
    )


def test_mark_lessons_and_history(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore.load(path)
    item = lesson()
    store.mark_lessons([item], seen_date=date(2026, 5, 2))
    store.save()

    loaded = SeenStore.load(path)

    assert "lesson:title:经典课程" in loaded.records
    assert "lesson:anchor:classic anchor" in loaded.records
    assert loaded.weekend_lesson_history() == [
        {
            "title": "经典课程",
            "topic": "GRB afterglow",
            "anchor_work": "classic anchor",
            "series_id": "grb-afterglow",
            "series_title": "GRB afterglow course",
            "part_index": "1",
            "planned_parts": "3",
            "lesson_scope": "Blast-wave dynamics",
        }
    ]


def test_weekend_history_keeps_legacy_records_compact(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text(
        '{"lesson:title:old": {"type": "weekend_lesson", "title": "old", "topic": "GRB", "anchor_work": "anchor", "first_seen": "2026-05-01"}}',
        encoding="utf-8",
    )

    loaded = SeenStore.load(path)

    assert loaded.weekend_lesson_history() == [
        {
            "title": "old",
            "topic": "GRB",
            "anchor_work": "anchor",
        }
    ]
