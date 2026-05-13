from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from astro_daily.config import load_settings
from astro_daily.feedback import VALID_RATINGS, append_feedback
from astro_daily.pipeline import DEFERRED_RETRY_EXIT_CODE, DeferredRetryNeeded, fetch_all_sources, run_pipeline
from src.clawbot_chat import run_clawbot_chat_loop, run_clawbot_chat_once
from src.clawbot_client import poll_clawbot_once
from src.push_clawbot import send_clawbot_report_message
from src.push_wecom_bot import send_wecom_markdown
from src.report_urls import latest_report_date


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s: %(message)s")
    try:
        if args.command == "run":
            run_date = date.fromisoformat(args.date) if args.date else None
            result = run_pipeline(
                config_path=args.config,
                run_date=run_date,
                dry_run=args.dry_run,
                ignore_seen=args.ignore_seen,
                defer_if_unfresh=args.defer_if_unfresh,
                final_attempt=args.final_attempt,
            )
            print(f"Report: {result.report_path}")
            print(f"HTML report: {result.html_report_path}")
            if result.published_url:
                print(f"Published URL: {result.published_url}")
            print(f"Fetched unique: {result.fetched_count}; new: {result.new_count}; kept: {result.kept_count}; supplemental: {result.supplemental_count}; classic lessons: {result.classic_lesson_count}")
            print(f"WeChat selected: {result.wechat_selected_count}; HE: {result.wechat_he_count}; length: {len(result.wechat_message)}")
            print("WeChat preview:")
            print(result.wechat_message)
            if result.source_errors:
                print("Source warnings:")
                for error in result.source_errors:
                    print(f"- {error}")
            return 0
        if args.command == "test-fetch":
            settings = load_settings(args.config)
            papers, errors = fetch_all_sources(settings)
            print(f"Fetched {len(papers)} papers")
            for paper in papers[:10]:
                category = f" [{paper.category}]" if paper.category else ""
                print(f"- {paper.source}{category}: {paper.title}")
            if errors:
                print("Warnings:")
                for error in errors:
                    print(f"- {error}")
            return 0 if papers else 1
        if args.command == "feedback":
            settings = load_settings(args.config)
            feedback_date = date.fromisoformat(args.date) if args.date else None
            record = append_feedback(
                settings.feedback_path,
                paper_id=args.paper_id,
                rating=args.rating,
                reason=args.reason or "",
                feedback_date=feedback_date,
            )
            print(f"Feedback saved: {record.rating} {record.paper_id} ({record.date.isoformat()})")
            print(f"Path: {settings.feedback_path}")
            return 0
        if args.command == "test-clawbot-send":
            settings = load_settings(args.config)
            run_date = date.fromisoformat(args.date) if args.date else latest_report_date(settings) or date.today()
            content = args.text or _clawbot_report_link_message(settings.site_base_url, run_date)
            send_clawbot_report_message(settings, content, dry_run=args.dry_run)
            print("ClawBot dry-run complete" if args.dry_run else "ClawBot message sent")
            return 0
        if args.command == "notify-update":
            settings = load_settings(args.config)
            content = _update_note_message(args.title, args.text)
            sent = []
            if settings.wechat.enabled:
                send_wecom_markdown(content, dry_run=args.dry_run)
                sent.append("wecom")
            if settings.clawbot.enabled:
                send_clawbot_report_message(settings, content, dry_run=args.dry_run)
                sent.append("clawbot")
            if sent:
                prefix = "Dry-run update notification: " if args.dry_run else "Update notification sent: "
                print(prefix + ", ".join(sent))
            else:
                print("No update notification channel enabled")
            return 0
        if args.command == "test-clawbot-poll":
            settings = load_settings(args.config)
            messages = poll_clawbot_once(settings)
            print(f"Received {len(messages)} ClawBot messages")
            for message in messages:
                token_state = "context_token=yes" if message.context_token else "context_token=no"
                print(f"- {message.sender_id} ({token_state}): {message.text}")
            return 0
        if args.command == "clawbot-chat":
            settings = load_settings(args.config)
            if args.once:
                replied = run_clawbot_chat_once(settings, dry_run=args.dry_run)
                print(f"ClawBot replies sent: {replied}")
                return 0
            run_clawbot_chat_loop(settings, poll_interval=args.poll_interval, dry_run=args.dry_run)
            return 0
        parser.print_help()
        return 1
    except DeferredRetryNeeded as exc:
        logging.getLogger(__name__).warning("Deferred retry requested: %s", exc)
        print(f"Deferred retry requested: {exc}")
        return DEFERRED_RETRY_EXIT_CODE
    except Exception as exc:
        logging.getLogger(__name__).error("%s", exc)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="astro-daily", description="Daily astronomy paper aggregation and WeChat push")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="Fetch, score, summarize, report, and optionally push")
    run.add_argument("--config", default="config.yaml")
    run.add_argument("--date", help="Override report date, YYYY-MM-DD")
    run.add_argument("--dry-run", action="store_true", help="Do not update seen_papers.json or send WeChat push")
    run.add_argument("--ignore-seen", action="store_true", help="Ignore seen_papers.json when re-testing a historical date")
    run.add_argument("--defer-if-unfresh", action="store_true", help="Exit with retry code before publishing if weekday arXiv freshness is unreliable")
    run.add_argument("--final-attempt", action="store_true", help="Bypass freshness deferral and publish the best available result")

    test_fetch = subparsers.add_parser("test-fetch", help="Fetch and parse configured sources without LLM calls")
    test_fetch.add_argument("--config", default="config.yaml")

    feedback = subparsers.add_parser("feedback", help="Record paper feedback for future recommendations")
    feedback.add_argument("--config", default="config.yaml")
    feedback.add_argument("rating", choices=sorted(VALID_RATINGS))
    feedback.add_argument("paper_id")
    feedback.add_argument("--reason", default="")
    feedback.add_argument("--date", help="Feedback/report date, YYYY-MM-DD")

    clawbot_send = subparsers.add_parser("test-clawbot-send", help="Send an existing report link or text through ClawBot")
    clawbot_send.add_argument("--config", default="config.yaml")
    clawbot_send.add_argument("--date", help="Report date for default link, YYYY-MM-DD")
    clawbot_send.add_argument("--text", help="Text to send instead of the default report link")
    clawbot_send.add_argument("--dry-run", action="store_true")

    notify_update = subparsers.add_parser("notify-update", help="Send a short GitHub/code backup update note to WeChat channels")
    notify_update.add_argument("--config", default="config.yaml")
    notify_update.add_argument("--title", default="Astro Daily 代码备份更新")
    notify_update.add_argument("--text", required=True, help="Short update note text")
    notify_update.add_argument("--dry-run", action="store_true")

    clawbot_poll = subparsers.add_parser("test-clawbot-poll", help="Poll ClawBot once and print received messages")
    clawbot_poll.add_argument("--config", default="config.yaml")

    clawbot_chat = subparsers.add_parser("clawbot-chat", help="Poll ClawBot messages, answer with LLM, and reply through WeChat")
    clawbot_chat.add_argument("--config", default="config.yaml")
    clawbot_chat.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between polling cycles")
    clawbot_chat.add_argument("--once", action="store_true", help="Run one poll-and-reply cycle, then exit")
    clawbot_chat.add_argument("--dry-run", action="store_true", help="Generate replies but do not send them")

    return parser


def _update_note_message(title: str, text: str) -> str:
    return "\n".join([f"**{title.strip()}**", "", text.strip()]).strip()


def _clawbot_report_link_message(site_base_url: str, run_date: date) -> str:
    return f"Astro Daily {run_date.isoformat()} 完整报告：\n{site_base_url.rstrip('/')}/reports/{run_date.isoformat()}.html"
