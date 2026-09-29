"""Historical price cache and returns matrix (foundation for Phase 4 analytics).

Stores daily closes in the price_history table and builds aligned price/return
matrices (positions + a market benchmark) used by the metrics, correlation and
scenario modules. The benchmark default is SPY (S&P 500 ETF) for beta/market
risk; it can be overridden per call.
"""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from connectors import market
from connectors.positions import get_tickers
from storage import PriceHistory, session_scope

logger = logging.getLogger(__name__)

BENCHMARK = "SPY"


def refresh_history(tickers: list[str], period: str = "1y") -> int:
    """Fetch daily closes for tickers and upsert into price_history.

    Returns the number of (ticker, date) rows written. Tickers that fail to
    fetch are logged and skipped.
    """
    written = 0
    with session_scope() as session:
        for t in tickers:
            closes = market.get_history(t, period=period)
            if not closes:
                logger.info("No history for %s; skipped", t)
                continue
            rows = [
                {
                    "ticker": t,
                    "date": datetime.fromisoformat(d),
                    "close": c,
                }
                for d, c in closes.items()
            ]
            stmt = sqlite_insert(PriceHistory).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker", "date"],
                set_={"close": stmt.excluded.close},
            )
            session.execute(stmt)
            written += len(rows)
    logger.info("Wrote %d price_history rows", written)
    return written


def refresh_portfolio_history(period: str = "1y") -> int:
    tickers = get_tickers()
    if BENCHMARK not in tickers:
        tickers = tickers + [BENCHMARK]
    return refresh_history(tickers, period=period)


def load_prices(tickers: list[str]) -> pd.DataFrame:
    """Wide price matrix from the cache: index=date, columns=tickers.

    Only dates present for a ticker are filled; callers align/dropna as needed.
    """
    if not tickers:
        return pd.DataFrame()
    with session_scope() as session:
        rows = (
            session.query(
                PriceHistory.ticker, PriceHistory.date, PriceHistory.close
            )
            .filter(PriceHistory.ticker.in_(tickers))
            .all()
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["ticker", "date", "close"])
    wide = df.pivot_table(index="date", columns="ticker", values="close")
    return wide.sort_index()


def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple daily returns, rows with any missing value dropped for alignment."""
    if prices.empty:
        return prices
    return prices.pct_change().dropna(how="any")
