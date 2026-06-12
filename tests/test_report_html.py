from pathlib import Path

from src.report_html import generate_html_report


def test_generate_html_report(tmp_path: Path):
    report_dir = tmp_path / "daily_reports"
    report_dir.mkdir()
    md_path = report_dir / "2026-05-02.md"
    md_path.write_text(
        """# Astro Daily 2026-05-02

## 高能天体物理重点

[link](https://example.com)

inline math: \\(\\dot{q}_{\\rm r}\\) and $\\gamma_{\\max}=2.0$

$$F_\\nu \\propto t^{-\\alpha}\\nu^{-\\beta}$$

![figure](https://example.com/figure.png)

<details class="paper-detail" markdown="1">
<summary>展开详细解读</summary>

#### 文章详细讲解

核心解读。

<details class="paper-subdetail" markdown="1">
<summary>展开背景、理论、公式、模型、章节和图表导读</summary>

#### 背景知识

- 第一条
- 第二条

</details>

</details>
""",
        encoding="utf-8",
    )
    html_path = Path(generate_html_report(str(md_path)))
    assert html_path == tmp_path / "docs" / "reports" / "2026-05-02.html"
    html = html_path.read_text(encoding="utf-8")
    assert '<meta charset="utf-8">' in html
    assert "2026-05-02" in html
    assert '<a href="https://example.com">link</a>' in html
    assert "Astro Daily 2026-05-02" not in html.split("<main>", 1)[1]
    assert 'class="report-nav"' in html
    assert 'class="home" href="../index.html"' in html
    assert '<details class="paper-detail">' in html
    assert '<details class="paper-subdetail">' in html
    assert '<details class="paper-subdetail" open>' not in html
    assert "tex-svg.js" in html
    assert "MathJax" in html
    assert 'class="math-display"' in html
    assert "\\(\\dot{q}_{\\rm r}\\)" in html
    assert "$\\gamma_{\\max}=2.0$" in html
    assert "<em" not in html
    assert '<img alt="figure" src="https://example.com/figure.png"' in html
    assert "<h4" in html
    assert "背景知识</h4>" in html

    index_path = tmp_path / "docs" / "index.html"
    index = index_path.read_text(encoding="utf-8")
    assert "2026-05-02" in index
    assert 'href="reports/2026-05-02.html"' in index
