from datetime import date, datetime, timezone

from astro_daily.llm import (
    SUMMARY_DEPTH_CONTRACT,
    WEEKEND_LESSON_DEPTH_CONTRACT,
    _paper_for_prompt,
    _parse_json_text,
    _weekend_lesson_outline_schema,
)
from astro_daily.models import Paper


def test_parse_json_repairs_unescaped_latex_backslashes():
    data = _parse_json_text(r'{"value": "公式 $$F_\nu \propto t^{-\alpha}$$ 和 \theta。"}')

    assert "\\nu" in data["value"]
    assert "\\alpha" in data["value"]
    assert "\\theta" in data["value"]


def test_parse_json_keeps_structural_quote_escapes():
    data = _parse_json_text('{"value": "他说：\\"ok\\""}')

    assert data["value"] == '他说："ok"'


def test_parse_json_repairs_raw_newlines_inside_strings():
    data = _parse_json_text('{"value": "第一段\n第二段"}')

    assert data["value"] == "第一段\n第二段"


def test_parse_json_repairs_trailing_commas():
    data = _parse_json_text('{"items": ["a", "b",],}')

    assert data == {"items": ["a", "b"]}


def test_parse_json_repairs_invalid_escape_at_error_position():
    data = _parse_json_text(r'{"value": "latex \(E_{\max}\) and \mathrm{eV}"}')

    assert data["value"] == r"latex \(E_{\max}\) and \mathrm{eV}"



def test_paper_prompt_includes_update_and_source_batch_dates():
    paper = Paper(
        paper_id="2605.10559",
        title="Neutrino source",
        url="https://arxiv.org/abs/2605.10559v1",
        source="arXiv",
        category="astro-ph.HE",
        published=datetime(2026, 5, 11, tzinfo=timezone.utc),
        updated=datetime(2026, 5, 11, tzinfo=timezone.utc),
        source_batch_date=date(2026, 5, 12),
    )

    payload = _paper_for_prompt(paper)

    assert payload["published"] == "2026-05-11T00:00:00+00:00"
    assert payload["updated"] == "2026-05-11T00:00:00+00:00"
    assert payload["source_batch_date"] == "2026-05-12"


def test_depth_contracts_require_systematic_formula_derivations():
    assert "6-12" in SUMMARY_DEPTH_CONTRACT["formula_derivation_cn"]
    assert "8-14" in WEEKEND_LESSON_DEPTH_CONTRACT["formula_derivation_cn"]
    assert "foundation-to-frontier" in WEEKEND_LESSON_DEPTH_CONTRACT["course_shape"]


def test_weekend_lesson_outline_schema_requires_course_skeleton():
    schema = _weekend_lesson_outline_schema()

    assert "chapter_outline" in schema["required"]
    assert schema["properties"]["chapter_outline"]["minItems"] >= 6
    assert schema["properties"]["derivation_ladder"]["minItems"] >= 8
