from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from astro_daily.config import load_settings
from astro_daily.pipeline import fetch_all_sources, run_pipeline


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s: %(message)s")
    try:
        if args.command == "run":
            run_date = date.fromisoformat(args.date) if args.date else None
            result = run_pipeline(config_path=args.config, run_date=run_date, dry_run=args.dry_run)
            print(f"Report: {result.report_path}")
            print(f"HTML report: {result.html_report_path}")
            if result.published_url:
                print(f"Published URL: {result.published_url}")
            print(f"Fetched unique: {result.fetched_count}; new: {result.new_count}; kept: {result.kept_count}")
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
        parser.print_help()
        return 1
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

    test_fetch = subparsers.add_parser("test-fetch", help="Fetch and parse configured sources without LLM calls")
    test_fetch.add_argument("--config", default="config.yaml")

    return parser
