from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime

from .config import Settings
from .models import TopicResult, parse_time, utc_now
from .pipeline import Pipeline
from .sample import seed_demo
from .storage.sqlite import SQLiteRepository


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="poe2-alpha", description="POE2 Reddit early trend / alpha detector")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Create or migrate the SQLite database")
    collect = sub.add_parser("collect", help="Collect approved Reddit API data")
    collect.add_argument("--no-comments", action="store_true")
    analyze = sub.add_parser("analyze", help="Analyze unprocessed posts and assign topics")
    analyze.add_argument("--as-of", help="UTC/ISO-8601 cutoff for replay-safe analysis")
    rank = sub.add_parser("rank", help="Show topic ranking")
    rank.add_argument("--as-of", help="UTC/ISO-8601 cutoff")
    rank.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    rank.add_argument("--limit", type=int, default=20)
    sub.add_parser("run-once", help="Collect, analyze, rank, and create console alerts")
    watch = sub.add_parser("watch", help="Run continuously; stop with Ctrl-C")
    watch.add_argument("--interval", type=int, help="Seconds between runs")
    demo = sub.add_parser("demo", help="Seed synthetic data and run the offline pipeline")
    demo.add_argument("--reset", action="store_true", help="Replace the configured local database")
    sub.add_parser("usage", help="Show recorded model token usage")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = Settings()
    repo = SQLiteRepository(settings.db_path)
    repo.initialize()
    pipeline = Pipeline(settings, repo)
    try:
        if args.command == "init-db":
            print(f"Initialized {settings.db_path}")
        elif args.command == "collect":
            print_report(pipeline.collect(with_comments=not args.no_comments))
        elif args.command == "analyze":
            print_report(pipeline.analyze(parse_time(args.as_of) if args.as_of else None))
        elif args.command == "rank":
            results, _ = pipeline.rank(parse_time(args.as_of) if args.as_of else None)
            print_results(results[:args.limit], args.json)
        elif args.command == "run-once":
            print_report(pipeline.run_once())
        elif args.command == "watch":
            interval = args.interval or settings.watch_interval_seconds
            while True:
                print_report(pipeline.run_once())
                time.sleep(max(60, interval))
        elif args.command == "demo":
            if args.reset:
                repo.clear()
            now = seed_demo(repo)
            offline = Pipeline(replace(settings, use_openai=False), repo)
            print_report(offline.analyze(now))
            results, _ = offline.rank(now, notify=True)
            print_results(results, False)
        elif args.command == "usage":
            for row in repo.usage_summary():
                print(f"{row['model']:<24} {row['operation']:<18} calls={row['calls']:<5} "
                      f"input={row['input_tokens']:<8} output={row['output_tokens']:<8} total={row['total_tokens']}")
        return 0
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def print_report(report: object) -> None:
    data = asdict(report)
    errors = data.pop("errors", [])
    print(" | ".join(f"{key}={value}" for key, value in data.items()))
    for error in errors:
        print(f"WARNING: {error}", file=sys.stderr)


def print_results(results: list[TopicResult], as_json: bool) -> None:
    if as_json:
        payload = []
        for result in results:
            raw = asdict(result)
            raw["first_detected"] = result.first_detected.isoformat()
            raw["latest_update"] = result.latest_update.isoformat()
            payload.append(raw)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not results:
        print("No ranked topics. Run collect/analyze or demo first.")
        return
    for index, result in enumerate(results, 1):
        print(f"\n{index}. {result.name}")
        print(f"   Alpha {result.alpha_score:.1f} | Trend {result.trend_score:.1f} | "
              f"Stage {result.stage_direction} | Confidence {result.confidence:.1f}")
        print(f"   Posts {result.related_posts} / Authors {result.unique_authors} | Market: {result.market_status}")
        print(f"   {result.summary}")
        print(f"   Why: {result.why_it_matters}")
        if result.core_items:
            print("   Core item candidates: " + ", ".join(
                f"{x.name} ({x.role}, demand {x.demand_concentration})" for x in result.core_items))
        if result.alert_reasons:
            print("   Alert: " + "; ".join(result.alert_reasons))
        print("   Breakdown: " + ", ".join(f"{k}={v:.1f}" for k, v in result.score_breakdown.items()))
        for url in result.representative_urls:
            print(f"   {url}")
