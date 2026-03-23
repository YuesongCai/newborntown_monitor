#!/usr/bin/env python3
"""
09911.HK Signal Monitoring System — Main Entry Point

Usage:
    python main.py              # Run full signal scan
    python main.py --dry-run    # Fetch data and compute indicators, skip notifications
    python main.py --json       # Output alerts as JSON to stdout

Schedule via cron (daily after HK market close at 16:30 HKT):
    30 16 * * 1-5 cd /path/to/newborntown_monitor && python main.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from src.data_fetcher import fetch_ohlcv
from src.indicators import compute_all
from src.signals import run_all_signals
from src.composite_signals import check_composite_signals
from src.notifier import dispatch_alerts, format_alert_json


def main() -> int:
    parser = argparse.ArgumentParser(description="09911.HK Signal Monitor")
    parser.add_argument("--dry-run", action="store_true", help="Skip notifications")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("main")

    # 1. Fetch data
    logger.info("Fetching OHLCV data...")
    df = fetch_ohlcv()

    # 2. Compute indicators
    logger.info("Computing technical indicators...")
    df = compute_all(df)

    # 3. Run individual signals
    logger.info("Running signal checks...")
    alerts = run_all_signals(df)

    # 4. Run composite signals
    composite_alerts = check_composite_signals(df, alerts)
    composite_ids = [a.signal_id for a in composite_alerts]
    alerts.extend(composite_alerts)

    # 5. Output
    if args.json:
        payloads = [format_alert_json(a) for a in alerts]
        for p in payloads:
            p["composite_signals_active"] = composite_ids
        print(json.dumps(payloads, ensure_ascii=False, indent=2))
        return 0

    if not alerts:
        logger.info("No signals triggered today.")
        print("No signals triggered.")
        return 0

    logger.info("%d signal(s) triggered.", len(alerts))

    if args.dry_run:
        for a in alerts:
            print(f"[DRY-RUN] {a.level}: {a.signal_id} — {a.signal_name}")
        return 0

    # 6. Dispatch
    dispatch_alerts(alerts, composite_ids)

    return 0


if __name__ == "__main__":
    sys.exit(main())
