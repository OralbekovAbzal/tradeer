"""Market data via yfinance (spec M2, Phase 1).

Quotes and sector lookups. Every call degrades gracefully: if yfinance is
unavailable or a ticker fails, we log and return None / skip rather than
crashing the dashboard (spec §13).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import yfinance as yf

    _YF_AVAILABLE = True
except Exception as exc:  # pragma: no cover - import-time environment issue
    yf = None  # type: ignore[assignment]
    _YF_AVAILABLE = False
    logger.warning("yfinance unavailable, market data disabled: %s", exc)


def is_available() -> bool:
    return _YF_AVAILABLE


def get_price(ticker: str) -> float | None:
    """Latest available close price for a ticker, or None on failure."""
    if not _YF_AVAILABLE:
        return None
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        if hist is None or hist.empty:
            logger.info("No price history for %s", ticker)
            return None
        return float(hist["Close"].dropna().iloc[-1])
    except Exception as exc:
        logger.warning("Price lookup failed for %s: %s", ticker, exc)
        return None


def get_prices(tickers: list[str]) -> dict[str, float | None]:
    return {t: get_price(t) for t in tickers}


def get_history(ticker: str, period: str = "1y") -> dict[str, float]:
    """Daily close history as {ISO date: close}. Empty dict on failure."""
    if not _YF_AVAILABLE:
        return {}
    try:
        hist = yf.Ticker(ticker).history(period=period)
        if hist is None or hist.empty:
            return {}
        closes = hist["Close"].dropna()
        return {idx.date().isoformat(): float(v) for idx, v in closes.items()}
    except Exception as exc:
        logger.warning("History lookup failed for %s: %s", ticker, exc)
        return {}


def get_sector(ticker: str) -> str | None:
    """Best-effort sector lookup; None if unavailable."""
    if not _YF_AVAILABLE:
        return None
    try:
        info = yf.Ticker(ticker).info
        return info.get("sector") if isinstance(info, dict) else None
    except Exception as exc:
        logger.info("Sector lookup failed for %s: %s", ticker, exc)
        return None
