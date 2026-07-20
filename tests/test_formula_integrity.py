from pathlib import Path

from astro_daily.formula_integrity import _normalize_line_broken_latex_rm, ensure_html_latex_formulas_valid, repair_formula_sections, repair_report_latex_formulas, validate_html_latex_formulas


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


def test_does_not_report_lines_inside_display_math_as_bare_latex():
    original = formula_section("\\[\nF_\\nu \\propto t^{-\\alpha}\n\\]")

    repaired, result = repair_formula_sections(original)

    assert repaired == original
    assert result.issue_count == 0


def test_repairs_double_escaped_inline_latex(tmp_path: Path):
    path = tmp_path / "2026-06-19.md"
    path.write_text(
        "# Astro Daily\n\n"
        "#### 文章详细讲解\n\n"
        "虽然 \\\\(8\\\\)PN 和 \\\\(f\\\\)-mode 是公式片段，\\\\(\\\\tilde{\\\\Lambda}\\\\) 也应正常渲染。\n",
        encoding="utf-8",
    )

    result = repair_report_latex_formulas(path)
    repaired = path.read_text(encoding="utf-8")

    assert "\\\\(8\\\\)PN" not in repaired
    assert "\\\\(f\\\\)-mode" not in repaired
    assert "\\(8\\)PN" in repaired
    assert "\\(f\\)-mode" in repaired
    assert "\\(\\tilde{\\Lambda}\\)" in repaired
    assert result.unresolved_count == 0


def test_repairs_json_escape_damaged_latex_control_characters(tmp_path: Path):
    path = tmp_path / "2026-07-08.md"
    damaged = (
        "公式被 JSON 转义污染后可能出现\n"
        "\\[\n"
        f"F=\\{chr(12)}rac{{E}}{{\\{chr(12)}rac{{1}}{{2}}}}+\\sin^2\\{chr(9)}heta_B+\\{chr(8)}ig[x]\n"
        "\\]"
    )
    path.write_text(formula_section(damaged), encoding="utf-8")

    result = repair_report_latex_formulas(path)
    repaired = path.read_text(encoding="utf-8")

    assert "\\frac{E}{\\frac{1}{2}}" in repaired
    assert "\\theta_B" in repaired
    assert "\\big[x]" in repaired
    assert chr(12) not in repaired
    assert chr(8) not in repaired
    assert chr(9) not in repaired
    assert result.unresolved_count == 0


def test_repairs_line_broken_rm_fragments(tmp_path: Path):
    path = tmp_path / "2026-07-09.md"
    damaged = (
        "第九步，计算量压缩可写为\n"
        "\\[\\nC_{\\\n"
        "m prune}=\\sum_m N_m^{\\\n"
        "m surv}c_m,\\qquad C_{\\\n"
        "m full}=\\sum_m N_m^{\\\n"
        "m all}c_m\n"
        "\\]\n"
        "E_{{\\\n"
        "m cut},i}\n"
        "其中 \\(N_m^{\\}}\\)\n"
        "m surv}\\) 是幸存模板数，\\(T_{\\}}\\)\n"
        "m coh}\\) 是相干时间。"
    )
    path.write_text(formula_section(damaged), encoding="utf-8")

    result = repair_report_latex_formulas(path)
    repaired = path.read_text(encoding="utf-8")

    assert "\\[\nC_{\\rm prune}" in repaired
    assert "N_m^{\\rm surv}c_m" in repaired
    assert "C_{\\rm full}" in repaired
    assert "N_m^{\\rm all}c_m" in repaired
    assert "E_{{\\rm cut},i}" in repaired
    assert "\\(N_m^{\\rm surv}\\)" in repaired
    assert "\\(T_{\\rm coh}\\)" in repaired
    assert result.unresolved_count == 0


def test_repairs_other_line_broken_latex_commands():
    slash = chr(92)
    damaged = "\\left(x" + slash + "\night) + S_" + slash + "\nu + \\" + "(" + slash + "\n\\(ho_0\\)\\)"

    repaired = _normalize_line_broken_latex_rm(damaged)

    assert "\\left(x\\right)" in repaired
    assert "S_\\nu" in repaired
    assert "\\(\\rho_0\\)" in repaired


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


def test_repairs_naked_inline_latex_across_report_prose(tmp_path: Path):
    path = tmp_path / "2026-05-10.md"
    path.write_text(
        "# Astro Daily\n\n"
        "#### 基础理论 / 方法脉络\n\n"
        "关键量包括自转能损失率 \\dot{E}、初始能库 W_0 和表面亮度 I_\\gamma(\\theta,E_\\gamma)。\n\n"
        "#### 模型拟合 / 应用方法\n\n"
        "若 D(E)=D_0(E/E_0)^\\delta 且 b(E)=b_0E^2，则约束 D_{\\rm in}。\n",
        encoding="utf-8",
    )

    result = repair_report_latex_formulas(path)
    repaired = path.read_text(encoding="utf-8")

    assert "\\(\\dot{E}\\)" in repaired
    assert "\\(W_0\\)" in repaired
    assert "\\(I_\\gamma(\\theta,E_\\gamma)\\)" in repaired
    assert "\\(D(E)=D_0(E/E_0)^\\delta\\)" in repaired
    assert "\\(b(E)=b_0E^2\\)" in repaired
    assert "\\(D_{\\rm in}\\)" in repaired
    assert result.repaired_count >= 6
    assert result.unresolved_count == 0


def test_bare_latex_repair_preserves_protected_markdown(tmp_path: Path):
    path = tmp_path / "2026-05-10.md"
    original = (
        "# Astro Daily\n\n"
        "#### 背景知识\n\n"
        "已有 \\(\\dot{E}\\) 和 $E_c$ 不应重复包裹。\n"
        "链接 [paper](https://example.com?q=E_c) 与 https://example.com/path_with_underscore 保持不变。\n"
        "运行 `latex \\dot{E}` 不应被包裹。\n"
        "![figure](https://example.com/Fig_1.png)\n"
        "```\n"
        "代码里的 \\gamma 不处理。\n"
        "```\n"
    )
    path.write_text(original, encoding="utf-8")

    result = repair_report_latex_formulas(path)
    repaired = path.read_text(encoding="utf-8")

    assert "\\(\\(\\dot{E}\\)\\)" not in repaired
    assert "$E_c$" in repaired
    assert "[paper](https://example.com?q=E_c)" in repaired
    assert "https://example.com/path_with_underscore" in repaired
    assert "`latex \\dot{E}`" in repaired
    assert "![figure](https://example.com/Fig_1.png)" in repaired
    assert "代码里的 \\gamma 不处理" in repaired
    assert result.issue_count == 0


def test_bare_latex_repair_skips_partial_complex_expressions(tmp_path: Path):
    path = tmp_path / "2026-05-16.md"
    original = (
        "# Astro Daily\n\n"
        "#### 背景知识\n\n"
        "Band 谱定义在 N(E)=dN/(dE dA dt) 上，低能段 N(E)=A(E/100 keV)^alpha exp(-E/E_0)。\n"
    )
    path.write_text(original, encoding="utf-8")

    result = repair_report_latex_formulas(path)
    repaired = path.read_text(encoding="utf-8")

    assert repaired == original
    assert result.issue_count == 0


def test_html_formula_validation_reports_naked_latex(tmp_path: Path):
    path = tmp_path / "bad.html"
    path.write_text("<main><p>自转能损失率 \\dot{E} 和 I_\\gamma(\\theta)。</p></main>", encoding="utf-8")

    result = validate_html_latex_formulas(path)

    assert result.unresolved_count == 1
    assert result.issues[0].kind == "naked_latex_html"


def test_html_formula_validation_accepts_delimited_latex(tmp_path: Path):
    path = tmp_path / "good.html"
    path.write_text("<main><p>自转能损失率 \\(\\dot{E}\\) 和 $I_\\gamma(\\theta)$。</p></main>", encoding="utf-8")

    result = ensure_html_latex_formulas_valid(path)

    assert result.issue_count == 0
