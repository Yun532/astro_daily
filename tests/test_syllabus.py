from astro_daily.seen import SeenStore
from astro_daily.syllabus import load_weekend_syllabus, select_next_weekend_lesson


def test_select_next_weekend_lesson_skips_seen_series_part(tmp_path):
    path = tmp_path / "weekend_syllabus.yaml"
    path.write_text(
        """
lessons:
  - id: first
    series_id: course
    series_title_cn: 系列课
    part_index: 1
    planned_parts: 2
    title_cn: 第一讲
    topic: topic one
    anchor_work_cn: anchor one
    lesson_scope_cn: scope one
    why_classic_cn: why one
  - id: second
    series_id: course
    series_title_cn: 系列课
    part_index: 2
    planned_parts: 2
    title_cn: 第二讲
    topic: topic two
    anchor_work_cn: anchor two
    lesson_scope_cn: scope two
    why_classic_cn: why two
""",
        encoding="utf-8",
    )
    seen = SeenStore(
        records={
            "lesson:title:first": {
                "type": "weekend_lesson",
                "title": "旧标题也可以",
                "series_id": "course",
                "part_index": 1,
            }
        },
        path=tmp_path / "seen.json",
    )

    selected = select_next_weekend_lesson(path, seen)

    assert selected is not None
    assert selected.id == "second"


def test_weekend_syllabus_prompt_contains_course_controls(tmp_path):
    path = tmp_path / "weekend_syllabus.yaml"
    path.write_text(
        """
lessons:
  - id: tde-01
    series_id: tde
    series_title_cn: TDE 课程
    part_index: 1
    planned_parts: 5
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

    entry = load_weekend_syllabus(path)[0]
    prompt = entry.to_prompt_topic()

    assert "STRICT_WEEKEND_SYLLABUS_LESSON" in prompt
    assert "TDE 第一讲" in prompt
    assert "rees-1988-tde" in prompt
