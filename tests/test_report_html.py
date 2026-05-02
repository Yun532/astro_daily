from pathlib import Path

from src.report_html import generate_html_report


def test_generate_html_report(tmp_path: Path):
    report_dir = tmp_path / "daily_reports"
    report_dir.mkdir()
    md_path = report_dir / "2026-05-02.md"
    md_path.write_text("# Astro Daily 2026-05-02\n\n## 高能天体物理重点\n\n[link](https://example.com)\n", encoding="utf-8")
    html_path = Path(generate_html_report(str(md_path)))
    assert html_path == tmp_path / "docs" / "reports" / "2026-05-02.html"
    html = html_path.read_text(encoding="utf-8")
    assert '<meta charset="utf-8">' in html
    assert "天文论文日报 2026-05-02" in html
    assert '<a href="https://example.com">link</a>' in html
