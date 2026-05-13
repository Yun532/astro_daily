from __future__ import annotations

from datetime import date, datetime
import re
from pathlib import Path

from astro_daily.config import Settings
from astro_daily.feedback import VALID_RATINGS, append_feedback, load_feedback
from src.report_urls import latest_report_date, report_url

LOG_LINE_LIMIT = 220
MAX_LOG_LINES = 12

_FEEDBACK_RE = re.compile(r"^(?:记录反馈|反馈)\s+(\S+)\s+(\S+)(?:\s+(.+))?$", re.IGNORECASE)
_WECHAT_ID_RE = re.compile(r"[A-Za-z0-9_\-]{8,}@im\.wechat")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)


def handle_console_command(settings: Settings, text: str) -> str | None:
    command = " ".join(text.strip().split())
    if not command:
        return None

    lowered = command.casefold()
    if lowered in {"帮助", "help", "菜单", "命令"}:
        return _help_text()
    if lowered in {"状态", "status"}:
        return _status_text(settings)
    if lowered in {"今天报告", "今日报告"}:
        return _today_report_text(settings)
    if lowered in {"最新报告", "最近报告", "报告链接"}:
        return _latest_report_text(settings)
    if lowered.startswith("查看日志") or lowered.startswith("日志"):
        return _log_text(settings, command)

    match = _FEEDBACK_RE.match(command)
    if match:
        return _record_feedback(settings, match.group(1), match.group(2), match.group(3) or "")

    return None


def _help_text() -> str:
    return "\n".join(
        [
            "Astro Daily 微信控制台可用命令：",
            "状态",
            "今天报告",
            "最新报告",
            "查看日志",
            "记录反馈 love/useful/skip/bad 论文ID 原因",
            "",
            "安全限制：微信端不会执行 shell，不会改源码、配置、.env，也不会上传 GitHub。",
        ]
    )


def _status_text(settings: Settings) -> str:
    latest_date = latest_report_date(settings)
    today_path = settings.root_dir / settings.publish.docs_dir / "reports" / f"{date.today().isoformat()}.html"
    feedback_count = len(load_feedback(settings.feedback_path))
    clawbot_log = _latest_file(settings.root_dir / settings.run_log.dir, "clawbot-chat-*.err.log")
    heartbeat = _format_mtime(clawbot_log) if clawbot_log else "无"
    latest = latest_date.isoformat() if latest_date else "无"
    today_state = "已生成" if today_path.exists() else "未生成"
    return "\n".join(
        [
            "Astro Daily 状态",
            f"最新报告：{latest}",
            f"今日报告：{today_state}",
            f"反馈记录：{feedback_count} 条",
            f"监听日志更新：{heartbeat}",
        ]
    )


def _today_report_text(settings: Settings) -> str:
    run_date = date.today()
    report_path = settings.root_dir / settings.publish.docs_dir / "reports" / f"{run_date.isoformat()}.html"
    url = report_url(settings.site_base_url, run_date)
    if report_path.exists():
        return f"今天报告：{url}"
    return f"今天报告还没有生成。\n预期链接：{url}"


def _latest_report_text(settings: Settings) -> str:
    run_date = latest_report_date(settings)
    if not run_date:
        return "还没有找到已生成的报告。"
    return f"最新报告（{run_date.isoformat()}）：{report_url(settings.site_base_url, run_date)}"


def _log_text(settings: Settings, command: str) -> str:
    count = _requested_log_line_count(command)
    log_dir = settings.root_dir / settings.run_log.dir
    pipeline = _latest_file(log_dir, "pipeline-*.jsonl")
    clawbot = _latest_file(log_dir, "clawbot-chat-*.err.log")
    parts = ["最近日志摘要："]
    if pipeline:
        parts.append(f"pipeline {pipeline.name}")
        parts.extend(_safe_tail(pipeline, count))
    else:
        parts.append("pipeline 无")
    if clawbot:
        parts.append(f"clawbot {clawbot.name}")
        parts.extend(_safe_tail(clawbot, min(count, 5)))
    else:
        parts.append("clawbot 无")
    return "\n".join(parts)


def _record_feedback(settings: Settings, rating: str, paper_id: str, reason: str) -> str:
    normalized_rating = rating.strip().casefold()
    if normalized_rating not in VALID_RATINGS:
        return f"反馈类型不支持：{rating}。可用：love/useful/skip/bad"
    try:
        record = append_feedback(settings.feedback_path, paper_id=paper_id, rating=normalized_rating, reason=reason)
    except ValueError as exc:
        return f"反馈没有保存：{exc}"
    return f"反馈已记录：{record.rating} {record.paper_id}"


def _requested_log_line_count(command: str) -> int:
    match = re.search(r"\b(\d{1,2})\b", command)
    if not match:
        return 6
    return max(1, min(int(match.group(1)), MAX_LOG_LINES))


def _latest_file(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    files = [path for path in directory.glob(pattern) if path.is_file()]
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def _safe_tail(path: Path, count: int) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [f"无法读取日志：{exc}"]
    return [_sanitize_log_line(line) for line in lines[-count:]]


def _sanitize_log_line(line: str) -> str:
    line = _BEARER_RE.sub("Bearer <redacted>", line)
    line = _WECHAT_ID_RE.sub("<wechat-user>", line)
    line = line.replace("\x00", "")
    if len(line) > LOG_LINE_LIMIT:
        return line[: LOG_LINE_LIMIT - 1].rstrip() + "..."
    return line


def _format_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
