from __future__ import annotations

from html import escape
from pathlib import Path
import re

import markdown


def generate_html_report(md_path: str) -> str:
    source = Path(md_path)
    markdown_text = source.read_text(encoding="utf-8")
    html_body = markdown.markdown(markdown_text, extensions=["extra", "sane_lists"])
    report_date = _date_from_path(source)
    title = f"天文论文日报 {report_date}"
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      background: #f6f7f9;
      color: #202124;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
      line-height: 1.6;
    }}
    main {{
      max-width: 920px;
      margin: 0 auto;
      background: #fff;
      padding: 28px;
      border-radius: 12px;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    }}
    h1 {{ font-size: 2rem; margin-top: 0; }}
    h2 {{
      margin-top: 2rem;
      padding-bottom: 0.35rem;
      border-bottom: 1px solid #e5e7eb;
      font-size: 1.45rem;
    }}
    h3 {{
      margin-top: 1.6rem;
      padding: 1rem;
      background: #f8fafc;
      border-left: 4px solid #3b82f6;
      border-radius: 8px;
      font-size: 1.15rem;
    }}
    a {{ color: #2563eb; word-break: break-word; }}
    details {{
      margin: 1rem 0 1.5rem;
      padding: 1rem;
      background: #fbfdff;
      border: 1px solid #dbeafe;
      border-radius: 10px;
    }}
    summary {{ cursor: pointer; font-weight: 700; }}
    blockquote {{
      margin-left: 0;
      padding: 0.8rem 1rem;
      background: #fff7ed;
      border-left: 4px solid #fb923c;
    }}
    code {{ background: #f1f5f9; padding: 0.1rem 0.25rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(title)}</h1>
    {html_body}
  </main>
</body>
</html>
"""
    target_dir = source.parent.parent / "docs" / "reports"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{source.stem}.html"
    target.write_text(html, encoding="utf-8")
    return str(target)


def _date_from_path(path: Path) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", path.stem)
    return match.group(0) if match else path.stem
