"""Periodic ingestion & alerting (spec M10, Phase 2).

A blocking APScheduler process that periodically:
  - refreshes prices (yfinance),
  - ingests news & earnings (Finnhub, if configured),
  - ingests Form 4 filings (SEC EDGAR),
  - runs the alert engine.

Run with:  py scheduler.py

Each job is wrapped so a failure in one source is logged and does not stop the
others or crash the scheduler (spec §13).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from alerts import engine as alert_engine
from connectors import filings, news
from connectors import positions as positions_io
from storage import init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("scheduler")

# Intervals in minutes. Kept simple; market-hours awareness can come later.
PRICE_REFRESH_MIN = 30
NEWS_REFRESH_MIN = 60
FILINGS_REFRESH_MIN = 360
ALERTS_MIN = 15


def _safe(name, fn):
    try:
        fn()
    except Exception:
        logger.exception("Job %s failed", name)


def job_prices():
    _safe("prices", lambda: positions_io.refresh_prices(lookup_sector=True))


def job_news():
    _safe("news", news.ingest_portfolio)


def job_filings():
    _safe("filings", filings.ingest_portfolio)


def job_alerts():
    _safe("alerts", alert_engine.run)


def build_scheduler() -> BlockingScheduler:
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(job_prices, "interval", minutes=PRICE_REFRESH_MIN, id="prices")
    sched.add_job(job_news, "interval", minutes=NEWS_REFRESH_MIN, id="news")
    sched.add_job(job_filings, "interval", minutes=FILINGS_REFRESH_MIN, id="filings")
    sched.add_job(job_alerts, "interval", minutes=ALERTS_MIN, id="alerts")
    return sched


def main() -> None:
    init_db()
    logger.info("Running initial ingestion pass...")
    job_prices()
    job_news()
    job_filings()
    job_alerts()
    sched = build_scheduler()
    logger.info("Scheduler started. Ctrl+C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
