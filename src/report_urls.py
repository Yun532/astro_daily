from __future__ import annotations

from datetime import date
from pathlib import Path
import re

from astro_daily.config import Settings

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.html$")


def report_url(site_base_url: str, run_date: date) -> str:
    return f"{site_base_url.rstrip('/')}/reports/{run_date.isoformat()}.html"


def latest_report_date(settings: Settings) -> date | None:
    reports_dir = settings.root_dir / settings.publish.docs_dir / "reports"
    if not reports_dir.exists():
        return None
    dates: list[date] = []
    for path in reports_dir.glob("*.html"):
        match = _DATE_RE.match(path.name)
        if not match:
            continue
        try:
            dates.append(date.fromisoformat(match.group(1)))
        except ValueError:
            continue
    return max(dates) if dates else None


def latest_report_url(settings: Settings, fallback_date: date | None = None) -> str:
    run_date = latest_report_date(settings) or fallback_date or date.today()
    return report_url(settings.site_base_url, run_date)
