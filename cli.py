"""Small CLI for Phase 1 tasks without the dashboard.

Examples:
    py cli.py init-db
    py cli.py import sample_data/positions_sample.csv
    py cli.py refresh
    py cli.py risk
"""
from __future__ import annotations

import argparse
import logging

from alerts import engine as alert_engine
from analysis import history, report as report_mod, research, risk
from connectors import filings, news
from connectors import positions as positions_io
from storage import init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trading Co-Pilot CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="Create the SQLite schema")

    p_import = sub.add_parser("import", help="Import positions from a CSV")
    p_import.add_argument("path")
    p_import.add_argument(
        "--append", action="store_true", help="Append instead of replacing"
    )

    sub.add_parser("refresh", help="Refresh prices via yfinance")
    sub.add_parser("risk", help="Print the current risk report")
    sub.add_parser("news", help="Ingest news & earnings (Finnhub)")
    sub.add_parser("filings", help="Ingest Form 4 filings (SEC EDGAR)")
    sub.add_parser("alerts", help="Run the alert engine once")

    sub.add_parser("refresh-history", help="Cache daily price history (yfinance)")
    sub.add_parser("digest", help="Print a Claude risk digest of the portfolio")

    p_report = sub.add_parser("report", help="Build the deep analytical report")
    p_report.add_argument(
        "--opinion", action="store_true", help="Include the optional Claude opinion"
    )
    p_report.add_argument(
        "--no-save", action="store_true", help="Print only, do not write to reports/"
    )

    args = parser.parse_args()
    init_db()

    if args.cmd == "init-db":
        print("Schema ready.")
    elif args.cmd == "import":
        n = positions_io.import_csv(args.path, replace=not args.append)
        print(f"Imported {n} positions.")
    elif args.cmd == "refresh":
        n = positions_io.refresh_prices(lookup_sector=True)
        print(f"Updated {n} positions.")
    elif args.cmd == "risk":
        report = risk.build_report()
        print(f"Portfolio value: ${report.total_value:,.2f}")
        print("Top positions:")
        for c in report.positions[:10]:
            print(f"  {c.ticker:<6} {c.weight:6.1%}  ${c.market_value:,.2f}")
        if report.flags:
            print("Flags:")
            for f in report.flags:
                print(f"  [{f.code}] {f.message}")
        else:
            print("No risk thresholds breached.")
    elif args.cmd == "news":
        result = news.ingest_portfolio()
        print(f"News: {result['news']} new, earnings: {result['earnings']} new.")
        if not news.is_available():
            print("(FINNHUB_API_KEY not set — source skipped.)")
    elif args.cmd == "filings":
        n = filings.ingest_portfolio()
        print(f"Form 4 filings: {n} new.")
    elif args.cmd == "alerts":
        n = alert_engine.run()
        print(f"Dispatched {n} new alerts.")
    elif args.cmd == "refresh-history":
        n = history.refresh_portfolio_history()
        print(f"Cached {n} price-history rows.")
    elif args.cmd == "digest":
        if not research.is_available():
            print("Claude disabled (no ANTHROPIC_API_KEY or SDK).")
        result = research.portfolio_digest()
        print(result.text)
    elif args.cmd == "report":
        md, path = report_mod.generate(
            include_opinion=args.opinion, save=not args.no_save
        )
        print(md)
        if path is not None:
            print(f"\nSaved to {path}")


if __name__ == "__main__":
    main()
