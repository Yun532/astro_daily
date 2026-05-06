from pathlib import Path

from astro_daily.formula_integrity import repair_formula_sections, repair_report_latex_formulas


def formula_section(body: str) -> str:
    return f"# Astro Daily\n\n#### 公式与推导\n\n{body}\n\n#### 模型拟合 / 应用方法\n\n后续内容。\n"


def test_repairs_missing_closing_inline_dollar():
    repaired, result = repair_formula_sections(formula_section("关键公式为 $F_\\nu \\propto t^{-\\alpha}，用于连接光变和谱指数。"))

    assert "关键公式为 $F_\\nu \\propto t^{-\\alpha}，用于连接光变和谱指数。$" in repaired
    assert result.repaired_count == 1
    assert result.unresolved_count == 0


def test_repairs_missing_display_dollar_pair():
    repaired, result = repair_formula_sections(formula_section("$$\nE \\sim \\Gamma^2 M c^2"))

    assert "$$\nE \\sim \\Gamma^2 M c^2\n\n$$\n#### 模型拟合" in repaired
    assert result.repaired_count == 1


def test_repairs_missing_inline_paren_delimiter():
    repaired, result = repair_formula_sections(formula_section("从 \\(E \\sim \\Gamma^2 M c^2 推出减速时间。"))

    assert "从 \\(E \\sim \\Gamma^2 M c^2 推出减速时间。\\)" in repaired
    assert result.repaired_count == 1


def test_repairs_missing_display_bracket_delimiter():
    repaired, result = repair_formula_sections(formula_section("\\[\nF_\\nu \\propto t^{-\\alpha}"))

    assert "\\[\nF_\\nu \\propto t^{-\\alpha}\n\n\\]\n#### 模型拟合" in repaired
    assert result.repaired_count == 1


def test_repairs_missing_group_closer_inside_math_span():
    repaired, result = repair_formula_sections(formula_section("$$F_\\nu \\propto t^{-\\alpha$$"))

    assert "$$F_\\nu \\propto t^{-\\alpha}$$" in repaired
    assert result.repaired_count == 1


def test_reports_bare_latex_but_does_not_change_it():
    original = formula_section("关键公式为 F_\\nu \\propto t^{-\\alpha}，但这里没有定界符。")

    repaired, result = repair_formula_sections(original)

    assert repaired == original
    assert result.repaired_count == 0
    assert result.unresolved_count == 1
    assert result.issues[0].kind == "bare_latex"


def test_does_not_touch_non_formula_sections():
    original = "# Astro Daily\n\n#### 背景知识\n\n关键公式为 $F_\\nu \\propto t^{-\\alpha}\n"

    repaired, result = repair_formula_sections(original)

    assert repaired == original
    assert result.checked_sections == 0
    assert result.issue_count == 0


def test_does_not_modify_markdown_links_or_images():
    original = formula_section("[arXiv](https://example.com?a=$x)\n![fig](https://example.com/f_$nu.png)")

    repaired, result = repair_formula_sections(original)

    assert repaired == original
    assert result.issue_count == 0


def test_repairs_report_file(tmp_path: Path):
    path = tmp_path / "2026-05-02.md"
    path.write_text(formula_section("关键公式为 $E \\sim \\Gamma^2 M c^2。"), encoding="utf-8")

    result = repair_report_latex_formulas(path)

    assert "$E \\sim \\Gamma^2 M c^2。$" in path.read_text(encoding="utf-8")
    assert result.repaired_count == 1
