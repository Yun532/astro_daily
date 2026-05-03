from pathlib import Path

from src.report_html import generate_html_report


def test_generate_html_report(tmp_path: Path):
    report_dir = tmp_path / "daily_reports"
    report_dir.mkdir()
    md_path = report_dir / "2026-05-02.md"
    md_path.write_text(
        "# Astro Daily 2026-05-02\n\n## 高能天体物理重点\n\n[link](https://example.com)\n\n$$F_\\nu \\propto t^{-\\alpha}\\nu^{-\\beta}$$\n\n![figure](https://example.com/figure.png)\n\n<details class=\"paper-detail\" markdown=\"1\">\n<summary>展开详细解读</summary>\n\n#### 背景知识\n\n- 第一条\n- 第二条\n\n</details>\n",
        encoding="utf-8",
    )
    html_path = Path(generate_html_report(str(md_path)))
    assert html_path == tmp_path / "docs" / "reports" / "2026-05-02.html"
    html = html_path.read_text(encoding="utf-8")
    assert '<meta charset="utf-8">' in html
    assert "天文论文日报 2026-05-02" in html
    assert '<a href="https://example.com">link</a>' in html
    assert "Astro Daily 2026-05-02" not in html.split("<main>", 1)[1]
    assert '<details class="paper-detail">' in html
    assert "tex-svg.js" in html
    assert "MathJax" in html
    assert 'class="math-display"' in html
    assert '<img alt="figure" src="https://example.com/figure.png"' in html
    assert "<h4" in html
    assert "背景知识</h4>" in html
