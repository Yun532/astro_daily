from __future__ import annotations

from dataclasses import dataclass, field
import re

from astro_daily.models import PaperSummary, ScoredPaper, WeekendLesson


PLACEHOLDER_MARKERS = (
    "Not provided",
    "automatic detailed explanation failed",
    "summary generation failed",
    "fallback summary",
    "auto-generated section was not reliable",
)
FORMULA_RE = re.compile(r"\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)", re.DOTALL)
SUMMARY_MIN_FORMULAS = 5
WEEKEND_LESSON_MIN_FORMULAS = 8


@dataclass(frozen=True)
class SummaryQualityResult:
    paper_id: str
    grounding_score: int
    depth_score: int
    clarity_score: int
    formula_quality: int
    figure_quality: int
    repair_needed: bool
    issues: list[str] = field(default_factory=list)

    def to_log_data(self) -> dict[str, object]:
        return {
            "paper_id": self.paper_id,
            "grounding_score": self.grounding_score,
            "depth_score": self.depth_score,
            "clarity_score": self.clarity_score,
            "formula_quality": self.formula_quality,
            "figure_quality": self.figure_quality,
            "repair_needed": self.repair_needed,
            "issues": self.issues,
        }


def check_summary_quality(items: list[ScoredPaper]) -> list[SummaryQualityResult]:
    return [_check_one(item) for item in items if item.summary]


def check_weekend_lesson_quality(lessons: list[WeekendLesson]) -> list[SummaryQualityResult]:
    return [_check_lesson(lesson, index) for index, lesson in enumerate(lessons, start=1)]


def quality_log_summary(results: list[SummaryQualityResult]) -> dict[str, object]:
    repair_needed = [result for result in results if result.repair_needed]
    return {
        "checked": len(results),
        "repair_needed": len(repair_needed),
        "min_depth_score": min((result.depth_score for result in results), default=None),
        "min_clarity_score": min((result.clarity_score for result in results), default=None),
        "issues": [result.to_log_data() for result in repair_needed],
    }


def _check_one(item: ScoredPaper) -> SummaryQualityResult:
    summary = item.summary
    assert summary is not None
    return _quality_from_fields(
        paper_id=item.paper.paper_id,
        fields=_required_fields(summary),
        formula_text=summary.formula_derivation_cn or "",
        related_work_text=summary.related_work_cn,
        key_sections_text=summary.key_sections_cn,
        figures_to_check_text=summary.figures_to_check_cn,
        key_figure_analysis_text=summary.key_figure_analysis_cn,
        min_formulas=SUMMARY_MIN_FORMULAS,
        formula_issue=f"formula_derivation_cn has fewer than {SUMMARY_MIN_FORMULAS} formulas",
    )


def _check_lesson(lesson: WeekendLesson, index: int) -> SummaryQualityResult:
    return _quality_from_fields(
        paper_id=f"weekend_lesson:{index}",
        fields=_lesson_required_fields(lesson),
        formula_text=lesson.formula_derivation_cn or "",
        related_work_text=lesson.followup_reading_cn,
        key_sections_text=lesson.key_sections_cn,
        figures_to_check_text=lesson.figures_to_check_cn,
        key_figure_analysis_text=lesson.key_figure_analysis_cn,
        min_formulas=WEEKEND_LESSON_MIN_FORMULAS,
        formula_issue=f"formula_derivation_cn has fewer than {WEEKEND_LESSON_MIN_FORMULAS} formulas",
    )


def _quality_from_fields(
    *,
    paper_id: str,
    fields: dict[str, str],
    formula_text: str,
    related_work_text: str,
    key_sections_text: str,
    figures_to_check_text: str,
    key_figure_analysis_text: str,
    min_formulas: int,
    formula_issue: str,
) -> SummaryQualityResult:
    issues: list[str] = []
    empty_fields = [name for name, value in fields.items() if not value.strip()]
    if empty_fields:
        issues.append("missing fields: " + ", ".join(empty_fields))
    short_fields = [name for name, value in fields.items() if 0 < len(value.strip()) < _minimum_length(name)]
    if short_fields:
        issues.append("too short: " + ", ".join(short_fields))
    joined = "\n".join(fields.values())
    if _has_placeholder(joined):
        issues.append("contains placeholder or fallback text")
    formula_count = len(FORMULA_RE.findall(formula_text))
    if formula_count < min_formulas:
        issues.append(formula_issue)
    if len(formula_text.strip()) < _minimum_length("formula_derivation_cn"):
        issues.append("formula_derivation_cn is too short for a foundation-to-paper derivation")
    if len((figures_to_check_text or "").strip()) < 120 and len((key_figure_analysis_text or "").strip()) < 220:
        issues.append("figure guidance is thin")
    depth_score = _score_from_lengths(fields)
    clarity_score = 6 if _has_placeholder(joined) else 8
    grounding_score = 7 if related_work_text or key_sections_text else 5
    formula_quality = min(10, 2 + formula_count)
    figure_quality = 8 if figures_to_check_text and key_figure_analysis_text else 5
    return SummaryQualityResult(
        paper_id=paper_id,
        grounding_score=grounding_score,
        depth_score=depth_score,
        clarity_score=clarity_score,
        formula_quality=formula_quality,
        figure_quality=figure_quality,
        repair_needed=bool(issues),
        issues=issues,
    )


def _required_fields(summary: PaperSummary) -> dict[str, str]:
    return {
        "summary_cn": summary.summary_cn,
        "why_important_cn": summary.why_important_cn,
        "value_cn": summary.value_cn,
        "why_care_cn": summary.why_care_cn,
        "detailed_explanation_cn": summary.detailed_explanation_cn,
        "background_cn": summary.background_cn,
        "basic_theory_cn": summary.basic_theory_cn,
        "formula_derivation_cn": summary.formula_derivation_cn,
        "model_fitting_cn": summary.model_fitting_cn,
        "key_sections_cn": summary.key_sections_cn,
        "figures_to_check_cn": summary.figures_to_check_cn,
        "key_figure_analysis_cn": summary.key_figure_analysis_cn,
        "related_work_cn": summary.related_work_cn,
    }


def _lesson_required_fields(lesson: WeekendLesson) -> dict[str, str]:
    return {
        "title_cn": lesson.title_cn,
        "why_classic_cn": lesson.why_classic_cn,
        "detailed_explanation_cn": lesson.detailed_explanation_cn,
        "background_cn": lesson.background_cn,
        "basic_theory_cn": lesson.basic_theory_cn,
        "formula_derivation_cn": lesson.formula_derivation_cn,
        "model_fitting_cn": lesson.model_fitting_cn,
        "key_sections_cn": lesson.key_sections_cn,
        "figures_to_check_cn": lesson.figures_to_check_cn,
        "key_figure_analysis_cn": lesson.key_figure_analysis_cn,
        "followup_reading_cn": lesson.followup_reading_cn,
        "next_lesson_suggestions_cn": lesson.next_lesson_suggestions_cn,
    }


def _minimum_length(name: str) -> int:
    if name == "title_cn":
        return 4
    if name in {"summary_cn", "why_important_cn", "value_cn", "why_care_cn"}:
        return 40
    if name in {"figures_to_check_cn", "key_figure_analysis_cn", "key_sections_cn"}:
        return 160
    if name == "formula_derivation_cn":
        return 500
    if name in {"basic_theory_cn", "model_fitting_cn", "detailed_explanation_cn", "background_cn", "followup_reading_cn"}:
        return 260
    return 160


def _score_from_lengths(fields: dict[str, str]) -> int:
    total = sum(min(len(value.strip()), 600) for value in fields.values())
    if total >= 3600:
        return 9
    if total >= 2600:
        return 8
    if total >= 1800:
        return 7
    if total >= 1000:
        return 6
    return 4


def _has_placeholder(text: str) -> bool:
    lowered = text.casefold()
    return any(marker.casefold() in lowered for marker in PLACEHOLDER_MARKERS)
