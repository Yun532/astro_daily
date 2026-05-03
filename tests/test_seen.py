from datetime import date

from astro_daily.models import Paper, WeekendLesson
from astro_daily.seen import SeenStore, deduplicate_papers


def paper(paper_id: str, title: str = "Title") -> Paper:
    return Paper(paper_id=paper_id, title=title, url=f"https://example.com/{paper_id}", source="test")


def lesson(title: str = "经典课程", anchor: str = "classic anchor") -> WeekendLesson:
    return WeekendLesson(
        topic="GRB afterglow",
        title_cn=title,
        anchor_work_cn=anchor,
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
        }
    ]
