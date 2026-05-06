from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
import re

import markdown


MARKDOWN_EXTENSIONS = ["extra", "sane_lists", "toc", "tables", "attr_list", "md_in_html", "nl2br"]


def generate_html_report(md_path: str) -> str:
    source = Path(md_path)
    markdown_text = source.read_text(encoding="utf-8")
    report_date = _date_from_path(source)
    title = f"天文论文日报 {report_date}"
    markdown_body, display_math_blocks = _prepare_math(_remove_top_heading(markdown_text))
    html_body = markdown.markdown(markdown_body, extensions=MARKDOWN_EXTENSIONS)
    html_body = _restore_display_math(html_body, display_math_blocks)
    target_dir = source.parent.parent / "docs" / "reports"
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #eef3fb;
      --panel: #ffffff;
      --panel-soft: #f8fbff;
      --text: #172033;
      --muted: #65758b;
      --line: #dce6f2;
      --blue: #2563eb;
      --blue-dark: #1e40af;
      --cyan: #0891b2;
      --amber: #d97706;
      --shadow: 0 18px 50px rgba(30, 64, 175, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(37, 99, 235, 0.16), transparent 32rem),
        radial-gradient(circle at top right, rgba(8, 145, 178, 0.12), transparent 28rem),
        var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
      line-height: 1.75;
    }}
    a {{ color: var(--blue); text-decoration-thickness: 0.08em; text-underline-offset: 0.18em; word-break: break-word; }}
    a:hover {{ color: var(--blue-dark); }}
    .page {{ max-width: 1080px; margin: 0 auto; padding: 32px 18px 56px; }}
    .hero {{
      position: relative;
      overflow: hidden;
      padding: 34px;
      border-radius: 28px;
      background: linear-gradient(135deg, #12213f 0%, #1d4ed8 52%, #0891b2 100%);
      color: #fff;
      box-shadow: var(--shadow);
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -80px -150px auto;
      width: 320px;
      height: 320px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.14);
    }}
    .report-nav {{ display: flex; justify-content: space-between; gap: 1rem; margin: 18px 0 0; }}
    .report-nav a,
    .report-nav span {{ flex: 1; padding: 0.85rem 1rem; border: 1px solid var(--line); border-radius: 16px; background: rgba(255, 255, 255, 0.86); box-shadow: 0 10px 24px rgba(30, 64, 175, 0.08); text-decoration: none; font-weight: 700; }}
    .report-nav .next {{ text-align: right; }}
    .report-nav span {{ color: var(--muted); background: rgba(248, 251, 255, 0.78); }}
    .eyebrow {{ margin: 0 0 10px; color: rgba(255, 255, 255, 0.78); font-size: 0.95rem; letter-spacing: 0.08em; text-transform: uppercase; }}
    h1 {{ position: relative; margin: 0; max-width: 760px; font-size: clamp(2rem, 5vw, 3.2rem); line-height: 1.15; }}
    .subtitle {{ position: relative; max-width: 760px; margin: 16px 0 0; color: rgba(255, 255, 255, 0.86); font-size: 1.05rem; }}
    main {{
      margin-top: 22px;
      padding: 28px;
      border: 1px solid rgba(220, 230, 242, 0.9);
      border-radius: 24px;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}
    main > p:first-child,
    main > p:nth-child(2) {{ color: var(--muted); }}
    h2 {{
      margin: 2.4rem 0 1rem;
      padding: 0.8rem 1rem;
      border: 1px solid var(--line);
      border-left: 6px solid var(--blue);
      border-radius: 16px;
      background: linear-gradient(90deg, #eff6ff, #ffffff);
      font-size: 1.45rem;
      line-height: 1.35;
    }}
    h2:first-child {{ margin-top: 0; }}
    h3 {{
      margin: 2rem 0 1rem;
      padding: 1.15rem 1.25rem;
      border: 1px solid #bfdbfe;
      border-radius: 18px;
      background: linear-gradient(135deg, #f8fbff, #eef6ff);
      box-shadow: 0 10px 24px rgba(37, 99, 235, 0.08);
      font-size: 1.18rem;
      line-height: 1.45;
    }}
    h4 {{ margin: 1.25rem 0 0.5rem; color: #0f3b7a; font-size: 1.02rem; }}
    ul, ol {{ padding-left: 1.35rem; }}
    li {{ margin: 0.3rem 0; }}
    main > ul {{
      padding: 1rem 1.2rem 1rem 2.2rem;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel-soft);
    }}
    strong {{ color: #0f2f5f; }}
    blockquote {{
      margin: 1rem 0;
      padding: 0.9rem 1rem;
      border: 1px solid #fed7aa;
      border-left: 5px solid #f97316;
      border-radius: 12px;
      background: #fff7ed;
      color: #7c2d12;
    }}
    code {{ background: #eaf1fb; padding: 0.12rem 0.3rem; border-radius: 6px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; overflow: hidden; border-radius: 12px; }}
    th, td {{ padding: 0.75rem; border: 1px solid var(--line); vertical-align: top; }}
    th {{ background: #eff6ff; }}
    mjx-container {{ overflow-x: auto; overflow-y: hidden; max-width: 100%; padding: 0.25rem 0; }}
    .math-display {{ margin: 1rem 0; overflow-x: auto; padding: 0.75rem 1rem; border: 1px solid #dbeafe; border-radius: 14px; background: #f8fbff; }}
    main img {{ max-width: 100%; height: auto; display: block; margin: 1rem auto; border: 1px solid var(--line); border-radius: 14px; box-shadow: 0 10px 24px rgba(15, 47, 95, 0.12); }}
    details.paper-detail {{
      margin: 1.25rem 0 1.9rem;
      border: 1px solid #b9d7ff;
      border-radius: 18px;
      background: linear-gradient(180deg, #fbfdff, #f3f8ff);
      box-shadow: 0 10px 24px rgba(37, 99, 235, 0.08);
      overflow: hidden;
    }}
    details.paper-detail[open] {{ border-color: #60a5fa; }}
    details.paper-detail summary {{
      cursor: pointer;
      list-style: none;
      padding: 1rem 1.15rem;
      background: linear-gradient(90deg, #dbeafe, #ecfeff);
      color: #173b73;
      font-weight: 800;
    }}
    details.paper-detail summary::-webkit-details-marker {{ display: none; }}
    details.paper-detail summary::before {{ content: "展开"; display: inline-block; margin-right: 0.65rem; padding: 0.12rem 0.5rem; border-radius: 999px; background: #2563eb; color: #fff; font-size: 0.78rem; }}
    details.paper-detail[open] summary::before {{ content: "收起"; background: #0891b2; }}
    details.paper-detail > *:not(summary) {{ margin-left: 1.15rem; margin-right: 1.15rem; }}
    details.paper-detail > :last-child {{ margin-bottom: 1.2rem; }}
    details.paper-detail h4 {{
      margin-top: 1.15rem;
      padding-top: 1rem;
      border-top: 1px dashed #bfdbfe;
    }}
    @media (max-width: 720px) {{
      .page {{ padding: 18px 10px 36px; }}
      .hero {{ padding: 24px 20px; border-radius: 22px; }}
      .report-nav {{ flex-direction: column; }}
      .report-nav .next {{ text-align: left; }}
      main {{ padding: 18px 14px; border-radius: 20px; }}
      h2 {{ font-size: 1.25rem; }}
      h3 {{ font-size: 1.05rem; }}
    }}
  </style>
  <script>
    window.MathJax = {{
      tex: {{ inlineMath: [['$', '$'], ['\\\\(', '\\\\)']], displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']] }},
      svg: {{ fontCache: 'global' }}
    }};
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
</head>
<body>
  <div class="page">
    <header class="hero">
      <p class="eyebrow">Astro Daily</p>
      <h1>{escape(title)}</h1>
      <p class="subtitle">面向天文与物理专业读者的每日论文筛选、中文解读与延伸阅读。</p>
    </header>
    {_report_nav_html(report_date, *_adjacent_report_dates(target_dir, report_date))}
    <main>
      {html_body}
    </main>
  </div>
</body>
</html>
"""
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{source.stem}.html"
    target.write_text(html, encoding="utf-8")
    _refresh_report_nav_links(target_dir)
    _refresh_index_page(target_dir.parent, target_dir)
    return str(target)


def _refresh_index_page(docs_dir: Path, reports_dir: Path) -> None:
    report_dates = _available_report_dates(reports_dir)
    latest_date = report_dates[-1] if report_dates else None
    latest_html = (
        f'<a class="latest-link" href="reports/{escape(latest_date)}.html">阅读最新日报：{escape(latest_date)}</a>'
        if latest_date
        else '<span class="latest-link disabled">暂无日报</span>'
    )
    archive_html = (
        "\n".join(
            f'          <li><a href="reports/{escape(report_date)}.html">天文论文日报 {escape(report_date)}</a></li>'
            for report_date in reversed(report_dates)
        )
        if report_dates
        else "          <li>暂无已发布日报。</li>"
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Astro Daily 天文论文日报</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #eef3fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #65758b;
      --line: #dce6f2;
      --blue: #2563eb;
      --blue-dark: #1e40af;
      --cyan: #0891b2;
      --shadow: 0 18px 50px rgba(30, 64, 175, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(37, 99, 235, 0.16), transparent 32rem),
        radial-gradient(circle at top right, rgba(8, 145, 178, 0.12), transparent 28rem),
        var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
      line-height: 1.75;
    }}
    a {{ color: var(--blue); text-decoration-thickness: 0.08em; text-underline-offset: 0.18em; }}
    a:hover {{ color: var(--blue-dark); }}
    .page {{ max-width: 1080px; margin: 0 auto; padding: 32px 18px 56px; }}
    .hero {{
      position: relative;
      overflow: hidden;
      padding: 40px;
      border-radius: 28px;
      background: linear-gradient(135deg, #12213f 0%, #1d4ed8 52%, #0891b2 100%);
      color: #fff;
      box-shadow: var(--shadow);
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -90px -150px auto;
      width: 330px;
      height: 330px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.14);
    }}
    .eyebrow {{ position: relative; margin: 0 0 10px; color: rgba(255, 255, 255, 0.78); font-size: 0.95rem; letter-spacing: 0.08em; text-transform: uppercase; }}
    h1 {{ position: relative; margin: 0; max-width: 760px; font-size: clamp(2.2rem, 6vw, 4rem); line-height: 1.12; }}
    .subtitle {{ position: relative; max-width: 760px; margin: 18px 0 0; color: rgba(255, 255, 255, 0.88); font-size: 1.08rem; }}
    .latest-link {{ position: relative; display: inline-block; margin-top: 26px; padding: 0.85rem 1.15rem; border-radius: 999px; background: #fff; color: #1e40af; text-decoration: none; font-weight: 800; box-shadow: 0 10px 24px rgba(15, 47, 95, 0.18); }}
    .latest-link.disabled {{ color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(280px, 0.85fr); gap: 22px; margin-top: 22px; }}
    .card {{ padding: 26px; border: 1px solid rgba(220, 230, 242, 0.9); border-radius: 24px; background: rgba(255, 255, 255, 0.92); box-shadow: var(--shadow); }}
    .card h2 {{ margin: 0 0 1rem; font-size: 1.35rem; color: #0f2f5f; }}
    .card p {{ color: var(--muted); }}
    .features {{ padding-left: 1.2rem; }}
    .features li {{ margin: 0.45rem 0; }}
    .archive {{ margin: 0; padding: 0; list-style: none; }}
    .archive li {{ border-top: 1px solid var(--line); }}
    .archive li:first-child {{ border-top: 0; }}
    .archive a {{ display: block; padding: 0.85rem 0; text-decoration: none; font-weight: 700; }}
    footer {{ margin-top: 24px; color: var(--muted); text-align: center; font-size: 0.92rem; }}
    @media (max-width: 780px) {{
      .page {{ padding: 18px 10px 36px; }}
      .hero {{ padding: 28px 22px; border-radius: 22px; }}
      .grid {{ grid-template-columns: 1fr; }}
      .card {{ padding: 20px 16px; border-radius: 20px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <header class="hero">
      <p class="eyebrow">Astro Daily</p>
      <h1>天文论文日报</h1>
      <p class="subtitle">面向天文与物理专业读者的每日论文筛选、中文深度解读、公式推导、图表导读与延伸阅读。</p>
      {latest_html}
    </header>
    <main class="grid">
      <section class="card">
        <h2>项目说明</h2>
        <p>Astro Daily 自动抓取 arXiv 与重要期刊 RSS，优先筛选高能天体物理、宇宙线、伽马射线、IACT、脉冲星、SNR、PWN 与 pulsar halo 等方向的论文，并生成适合专业读者阅读的中文报告。</p>
        <ul class="features">
          <li>工作日：聚焦当天或近期值得关注的新论文。</li>
          <li>周末或 arXiv 安静日：生成经典论文课程式深度讲解。</li>
          <li>报告包含科学背景、核心结果、模型拟合、公式与关键图表导读。</li>
        </ul>
      </section>
      <section class="card">
        <h2>报告归档</h2>
        <ul class="archive">
{archive_html}
        </ul>
      </section>
    </main>
    <footer>GitHub Pages 静态主页 · 自动随日报生成刷新</footer>
  </div>
</body>
</html>
"""
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "index.html").write_text(html, encoding="utf-8")


def _refresh_report_nav_links(target_dir: Path) -> None:
    report_dates = _available_report_dates(target_dir)
    for index, report_date in enumerate(report_dates):
        path = target_dir / f"{report_date}.html"
        html = path.read_text(encoding="utf-8")
        previous_date = report_dates[index - 1] if index > 0 else None
        next_date = report_dates[index + 1] if index + 1 < len(report_dates) else None
        nav_html = _report_nav_html(report_date, previous_date, next_date)
        html = _replace_report_nav(html, nav_html)
        path.write_text(html, encoding="utf-8")


def _replace_report_nav(html: str, nav_html: str) -> str:
    pattern = r"\n\s*<!-- REPORT_NAV_START -->[\s\S]*?<!-- REPORT_NAV_END -->"
    if re.search(pattern, html):
        return re.sub(pattern, "\n    " + nav_html, html, count=1)
    return html.replace("\n    <main>", "\n    " + nav_html + "\n    <main>", 1)


def _report_nav_html(report_date: str, previous_date: str | None, next_date: str | None) -> str:
    previous = (
        f'<a class="previous" href="{previous_date}.html">← 上一期：{previous_date}</a>'
        if previous_date
        else '<span class="previous">← 没有更早的报告</span>'
    )
    next_link = (
        f'<a class="next" href="{next_date}.html">下一期：{next_date} →</a>'
        if next_date
        else '<span class="next">没有更新的报告 →</span>'
    )
    return f'<!-- REPORT_NAV_START -->\n    <nav class="report-nav" aria-label="日报前后导航" data-report-date="{escape(report_date)}">\n      {previous}\n      {next_link}\n    </nav>\n    <!-- REPORT_NAV_END -->'


def _adjacent_report_dates(target_dir: Path, report_date: str) -> tuple[str | None, str | None]:
    report_dates = _available_report_dates(target_dir)
    if report_date not in report_dates:
        report_dates.append(report_date)
        report_dates.sort()
    index = report_dates.index(report_date)
    previous_date = report_dates[index - 1] if index > 0 else None
    next_date = report_dates[index + 1] if index + 1 < len(report_dates) else None
    return previous_date, next_date


def _available_report_dates(target_dir: Path) -> list[str]:
    if not target_dir.exists():
        return []
    dates: list[str] = []
    for path in target_dir.glob("*.html"):
        try:
            date.fromisoformat(path.stem)
        except ValueError:
            continue
        dates.append(path.stem)
    return sorted(dates)


def _prepare_math(markdown_text: str) -> tuple[str, list[str]]:
    math_blocks: list[str] = []

    def placeholder_for(block: str) -> str:
        placeholder = f"@@ASTRO_MATH_{len(math_blocks)}@@"
        math_blocks.append(block)
        return placeholder

    def replace_display(match: re.Match[str]) -> str:
        content = (match.group(1) or match.group(2) or "").strip()
        block = f'<div class="math-display">\\[{content}\\]</div>'
        return f"\n\n{placeholder_for(block)}\n\n"

    def replace_inline_paren(match: re.Match[str]) -> str:
        return placeholder_for(f"\\({match.group(1)}\\)")

    def replace_inline_dollar(match: re.Match[str]) -> str:
        return placeholder_for(f"${match.group(1)}$")

    text = re.sub(r"\\\[([\s\S]*?)\\\]|\$\$([\s\S]*?)\$\$", replace_display, markdown_text)
    text = re.sub(r"\\\((.*?)\\\)", replace_inline_paren, text)
    text = re.sub(r"(?<!\\)(?<!\$)\$(?!\$)(.*?)(?<!\\)(?<!\$)\$(?!\$)", replace_inline_dollar, text)
    return text, math_blocks


def _restore_display_math(html: str, display_blocks: list[str]) -> str:
    for index, block in enumerate(display_blocks):
        placeholder = f"@@ASTRO_MATH_{index}@@"
        html = html.replace(f"<p>{placeholder}</p>", block).replace(placeholder, block)
    return html


def _remove_top_heading(markdown_text: str) -> str:
    return re.sub(r"\A# .+?(?:\r?\n)+", "", markdown_text, count=1)


def _date_from_path(path: Path) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", path.stem)
    return match.group(0) if match else path.stem
