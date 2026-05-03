from __future__ import annotations

from typing import Any, List

from astro_daily.models import Paper, WeekendLesson

MAX_WECOM_BYTES = 3800


def compress_for_wechat(papers: List[Paper], date: str, report_url: str) -> str:
    items = _select_candidates(papers)
    for count in range(min(5, len(items)), 2, -1):
        text = _render(items[:count], date, report_url, short=False)
        if _byte_len(text) <= MAX_WECOM_BYTES:
            return text
    count = min(3, len(items))
    text = _render(items[:count], date, report_url, short=True)
    if _byte_len(text) <= MAX_WECOM_BYTES:
        return text
    suffix = f"\n\n[完整报告]({report_url})"
    return _fit_bytes(text, MAX_WECOM_BYTES - _byte_len(suffix)).rstrip() + suffix


def compress_weekend_lessons(lessons: list[WeekendLesson], date: str, report_url: str) -> str:
    lines = [
        f"# 天文日报｜{date}",
        "",
        f"周末经典专题课：{len(lessons)} 讲",
        "今天 arXiv 通常不更新，改为精讲高能天体物理经典工作。",
        "",
    ]
    for index, lesson in enumerate(lessons[:3], start=1):
        lines.extend([
            f"{index}. **{lesson.title_cn}**",
            f"主题：{lesson.topic}",
            f"经典性：{_trim(lesson.why_classic_cn, 120)}",
            "",
        ])
    lines.append(f"[完整报告]({report_url})")
    text = "\n".join(lines).strip()
    if _byte_len(text) <= MAX_WECOM_BYTES:
        return text
    suffix = f"\n\n[完整报告]({report_url})"
    return _fit_bytes(text, MAX_WECOM_BYTES - _byte_len(suffix)).rstrip() + suffix


def select_wechat_papers(papers: list[Any]) -> list[Any]:
    return _select_candidates(papers)[:5]


def wechat_category_counts(papers: list[Any]) -> tuple[int, int, int]:
    he = sum(1 for item in papers if _paper(item).category == "astro-ph.HE")
    instrument = sum(1 for item in papers if _paper(item).category == "astro-ph.IM")
    other = len(papers) - he - instrument
    return he, instrument, other


def _select_candidates(papers: list[Any]) -> list[Any]:
    candidates = [item for item in papers if _final_score(item) >= _minimum_score(item)]
    if not candidates:
        candidates = list(papers)
    return sorted(candidates, key=lambda item: (_final_score(item), _paper(item).category == "astro-ph.HE"), reverse=True)


def _minimum_score(item: Any) -> float:
    paper = _paper(item)
    if paper.category == "astro-ph.HE":
        return 0.0
    return 8.0


def _render(items: list[Any], date: str, report_url: str, *, short: bool) -> str:
    he, instrument, other = wechat_category_counts(items)
    lines = [
        f"# 天文日报｜{date}",
        "",
        f"今日精选：{len(items)} 篇  ",
        f"HE：{he} 篇｜仪器：{instrument} 篇｜其他：{other} 篇",
        "",
    ]
    for index, item in enumerate(items, start=1):
        paper = _paper(item)
        summary = getattr(item, "summary", None)
        lines.extend([
            f"{index}. **{paper.title}**",
            f"一段话：{_summary_text(item, short=short)}",
            f"重要性：{_importance_text(item, short=short)}",
            f"[阅读全文]({paper.url})",
            "",
        ])
    lines.append(f"[完整报告]({report_url})")
    return "\n".join(lines).strip()


def _summary_text(item: Any, *, short: bool) -> str:
    summary = getattr(item, "summary", None)
    paper = _paper(item)
    text = ""
    if summary and getattr(summary, "summary_cn", ""):
        text = summary.summary_cn
    else:
        text = paper.abstract or paper.title
    return _trim(text, 90 if short else 150)


def _importance_text(item: Any, *, short: bool) -> str:
    summary = getattr(item, "summary", None)
    reason = getattr(getattr(item, "score", None), "reason", "")
    text = ""
    if summary and getattr(summary, "why_important_cn", ""):
        text = summary.why_important_cn
    else:
        text = reason or "这篇论文在今天的候选论文中评分较高，值得优先阅读。"
    return _trim(text, 60 if short else 100)


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _fit_bytes(text: str, byte_limit: int) -> str:
    if _byte_len(text) <= byte_limit:
        return text
    result = ""
    for character in text:
        if _byte_len(result + character + "…") > byte_limit:
            break
        result += character
    return result.rstrip("，。；、 \n") + "…"


def _trim(text: str, limit: int) -> str:
    normalized = " ".join(str(text).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip("，。；、 ") + "…"


def _paper(item: Any) -> Paper:
    return getattr(item, "paper", item)


def _final_score(item: Any) -> float:
    score = getattr(item, "score", None)
    if score is not None:
        return float(getattr(score, "final_score", 0.0))
    return float(getattr(item, "final_score", 0.0))
