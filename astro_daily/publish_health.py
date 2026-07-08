from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import re

from astro_daily.config import Settings
from astro_daily.formula_integrity import validate_html_latex_formulas

MAX_WECOM_BYTES = 3800
REPLACEMENT_CHARACTER = "\ufffd"
REPEATED_QUESTION_RE = re.compile(r"\?{4,}")
MOJIBAKE_MARKERS = ("锛", "绡", "鏃", "瀹", "闃", "涓", "浠", "璁", "鐞", "鎶")


@dataclass(frozen=True)
class PublishHealthIssue:
    kind: str
    message: str
    severity: str = "error"
    snippet: str = ""


@dataclass
class PublishHealthResult:
    html_path: str
    checks: int = 0
    issues: list[PublishHealthIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def to_log_data(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": self.checks,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [
                {
                    "kind": issue.kind,
                    "severity": issue.severity,
                    "message": issue.message,
                    "snippet": issue.snippet,
                }
                for issue in self.issues
            ],
        }


class PublishHealthError(RuntimeError):
    def __init__(self, result: PublishHealthResult):
        first = result.issues[0].message if result.issues else "unknown health check failure"
        super().__init__(f"Publish health check failed: {first}")
        self.result = result


def ensure_publish_health(
    *,
    settings: Settings,
    html_report_path: str | Path,
    wechat_message: str,
    report_url: str,
    max_wechat_bytes: int = MAX_WECOM_BYTES,
) -> PublishHealthResult:
    result = validate_publish_health(
        settings=settings,
        html_report_path=html_report_path,
        wechat_message=wechat_message,
        report_url=report_url,
        max_wechat_bytes=max_wechat_bytes,
    )
    if not result.ok:
        raise PublishHealthError(result)
    return result


def validate_publish_health(
    *,
    settings: Settings,
    html_report_path: str | Path,
    wechat_message: str,
    report_url: str,
    max_wechat_bytes: int = MAX_WECOM_BYTES,
) -> PublishHealthResult:
    html_path = Path(html_report_path)
    result = PublishHealthResult(html_path=str(html_path))
    html = html_path.read_text(encoding="utf-8")

    _check_html_formulas(html_path, result)
    _check_text_encoding("html", html, result)
    _check_local_images(settings=settings, html_path=html_path, html=html, result=result)
    _check_wechat_message(wechat_message, report_url, max_wechat_bytes, result)
    return result


def _check_html_formulas(html_path: Path, result: PublishHealthResult) -> None:
    result.checks += 1
    formula_result = validate_html_latex_formulas(html_path)
    for issue in formula_result.issues:
        if issue.repaired:
            continue
        result.issues.append(
            PublishHealthIssue(
                kind="html_formula",
                message=issue.message,
                snippet=issue.snippet,
            )
        )


def _check_text_encoding(label: str, text: str, result: PublishHealthResult) -> None:
    result.checks += 1
    if REPLACEMENT_CHARACTER in text:
        result.issues.append(
            PublishHealthIssue(
                kind=f"{label}_encoding_replacement_char",
                message=f"{label} contains Unicode replacement characters",
                snippet=_snippet_around(text, REPLACEMENT_CHARACTER),
            )
        )
    repeated = REPEATED_QUESTION_RE.search(text)
    if repeated and _question_ratio(text) > 0.005:
        result.issues.append(
            PublishHealthIssue(
                kind=f"{label}_repeated_question_marks",
                message=f"{label} looks like non-ASCII text was replaced by question marks",
                snippet=_snippet_around(text, repeated.group(0)),
            )
        )
    marker_count = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    if marker_count >= 12 and marker_count / max(len(text), 1) > 0.005:
        result.issues.append(
            PublishHealthIssue(
                kind=f"{label}_mojibake_markers",
                message=f"{label} contains many common UTF-8/GBK mojibake markers",
                snippet=_first_mojibake_snippet(text),
            )
        )


def _check_wechat_message(wechat_message: str, report_url: str, max_wechat_bytes: int, result: PublishHealthResult) -> None:
    _check_text_encoding("wechat", wechat_message, result)
    result.checks += 1
    byte_len = len(wechat_message.encode("utf-8"))
    if byte_len > max_wechat_bytes:
        result.issues.append(
            PublishHealthIssue(
                kind="wechat_too_long",
                message=f"WeCom markdown message is {byte_len} bytes, above {max_wechat_bytes}",
            )
        )
    if report_url and report_url not in wechat_message:
        result.issues.append(
            PublishHealthIssue(
                kind="wechat_missing_report_url",
                message="WeCom markdown message does not include the report URL",
                snippet=wechat_message[:160],
            )
        )
    if not _contains_cjk(wechat_message) and REPEATED_QUESTION_RE.search(wechat_message):
        result.issues.append(
            PublishHealthIssue(
                kind="wechat_missing_chinese_with_questions",
                message="WeCom markdown has repeated question marks and almost no Chinese text",
                snippet=wechat_message[:160],
            )
        )


def _check_local_images(*, settings: Settings, html_path: Path, html: str, result: PublishHealthResult) -> None:
    result.checks += 1
    parser = _ImageSrcParser()
    parser.feed(html)
    missing: list[str] = []
    for src in parser.image_sources:
        if _is_external_or_embedded(src):
            continue
        image_path = _resolve_html_asset(settings=settings, html_path=html_path, src=src)
        if not image_path.exists():
            missing.append(src)
    for src in missing[:10]:
        result.issues.append(
            PublishHealthIssue(
                kind="missing_local_image",
                message=f"HTML references a missing local image: {src}",
            )
        )
    if len(missing) > 10:
        result.issues.append(
            PublishHealthIssue(
                kind="missing_local_image_overflow",
                message=f"HTML has {len(missing) - 10} additional missing local images",
            )
        )


class _ImageSrcParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.image_sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        for name, value in attrs:
            if name.lower() == "src" and value:
                self.image_sources.append(value)


def _resolve_html_asset(*, settings: Settings, html_path: Path, src: str) -> Path:
    clean_src = src.split("#", 1)[0].split("?", 1)[0]
    path = Path(clean_src)
    if path.is_absolute():
        return path
    if clean_src.startswith("/"):
        return settings.root_dir / settings.publish.docs_dir / clean_src.lstrip("/")
    return html_path.parent / clean_src


def _is_external_or_embedded(src: str) -> bool:
    lowered = src.lower()
    return lowered.startswith(("http://", "https://", "data:", "mailto:", "#"))


def _question_ratio(text: str) -> float:
    return text.count("?") / max(len(text), 1)


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _snippet_around(text: str, needle: str, radius: int = 60) -> str:
    index = text.find(needle)
    if index == -1:
        return text[: radius * 2]
    start = max(0, index - radius)
    end = min(len(text), index + len(needle) + radius)
    return text[start:end].replace("\n", " ")[:160]


def _first_mojibake_snippet(text: str) -> str:
    positions = [text.find(marker) for marker in MOJIBAKE_MARKERS if marker in text]
    return _snippet_around(text, text[min(position for position in positions if position >= 0)])
