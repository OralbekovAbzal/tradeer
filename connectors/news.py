"""News & earnings calendar via Finnhub (spec M2, Phase 2).

Pulls company news and upcoming earnings dates for portfolio tickers. The API
key is read directly from the environment (FINNHUB_API_KEY) and never logged.
If the key is missing or a request fails, the source degrades gracefully: we
log and skip rather than crashing (spec §3, §13).

Only public data is used.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

from config import get_settings
from connectors.positions import get_tickers
from storage import Event, News, session_scope

logger = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"
_TIMEOUT = 15


def _api_key() -> str | None:
    key = os.getenv("FINNHUB_API_KEY")
    return key.strip() if key else None


def is_available() -> bool:
    return _api_key() is not None


@dataclass
class ParsedNews:
    ticker: str
    headline: str
    url: str | None
    source: str | None
    published_at: datetime | None


@dataclass
class ParsedEarnings:
    ticker: str
    event_date: datetime | None
    payload: str  # JSON string with eps/revenue estimates etc.


def _get(path: str, params: dict) -> list | dict | None:
    key = _api_key()
    if key is None:
        logger.info("FINNHUB_API_KEY not set; skipping %s", path)
        return None
    try:
        resp = requests.get(
            f"{_BASE}{path}", params={**params, "token": key}, timeout=_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Finnhub request failed (%s): %s", path, exc)
        return None


def normalize_news(raw: list | None, ticker: str) -> list[ParsedNews]:
    """Convert Finnhub /company-news payload into ParsedNews. Pure function."""
    out: list[ParsedNews] = []
    if not raw:
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        headline = (item.get("headline") or "").strip()
        if not headline:
            continue
        ts = item.get("datetime")
        published = (
            datetime.fromtimestamp(ts, tz=timezone.utc)
            if isinstance(ts, (int, float)) and ts > 0
            else None
        )
        out.append(
            ParsedNews(
                ticker=ticker,
                headline=headline,
                url=item.get("url") or None,
                source=item.get("source") or None,
                published_at=published,
            )
        )
    return out


def normalize_earnings(raw: dict | None) -> list[ParsedEarnings]:
    """Convert Finnhub /calendar/earnings payload into ParsedEarnings. Pure."""
    import json

    out: list[ParsedEarnings] = []
    if not raw:
        return out
    for item in raw.get("earningsCalendar", []) or []:
        if not isinstance(item, dict):
            continue
        ticker = (item.get("symbol") or "").upper()
        if not ticker:
            continue
        date_str = item.get("date")
        event_date = None
        if date_str:
            try:
                event_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pass
        out.append(
            ParsedEarnings(
                ticker=ticker,
                event_date=event_date,
                payload=json.dumps(
                    {
                        "epsEstimate": item.get("epsEstimate"),
                        "epsActual": item.get("epsActual"),
                        "revenueEstimate": item.get("revenueEstimate"),
                        "hour": item.get("hour"),
                    }
                ),
            )
        )
    return out


def fetch_news(ticker: str, lookback_days: int | None = None) -> list[ParsedNews]:
    days = lookback_days or get_settings().news_lookback_days
    today = datetime.now(timezone.utc).date()
    frm = (today - timedelta(days=days)).isoformat()
    raw = _get(
        "/company-news", {"symbol": ticker, "from": frm, "to": today.isoformat()}
    )
    return normalize_news(raw if isinstance(raw, list) else None, ticker)


def fetch_earnings(ticker: str, lookahead_days: int | None = None) -> list[ParsedEarnings]:
    days = lookahead_days or get_settings().earnings_lookahead_days
    today = datetime.now(timezone.utc).date()
    to = (today + timedelta(days=days)).isoformat()
    raw = _get(
        "/calendar/earnings",
        {"symbol": ticker, "from": today.isoformat(), "to": to},
    )
    return normalize_earnings(raw if isinstance(raw, dict) else None)


def _persist_news(items: list[ParsedNews]) -> int:
    """Insert news, skipping duplicates by (ticker, headline, published_at)."""
    saved = 0
    with session_scope() as session:
        for n in items:
            exists = (
                session.query(News.id)
                .filter(
                    News.ticker == n.ticker,
                    News.headline == n.headline,
                    News.published_at == n.published_at,
                )
                .first()
            )
            if exists:
                continue
            session.add(
                News(
                    ticker=n.ticker,
                    headline=n.headline,
                    url=n.url,
                    source=n.source,
                    published_at=n.published_at,
                )
            )
            saved += 1
    return saved


def _persist_earnings(items: list[ParsedEarnings]) -> int:
    """Insert earnings events, deduping by (ticker, type, event_date)."""
    saved = 0
    with session_scope() as session:
        for e in items:
            exists = (
                session.query(Event.id)
                .filter(
                    Event.ticker == e.ticker,
                    Event.type == "earnings",
                    Event.event_date == e.event_date,
                )
                .first()
            )
            if exists:
                continue
            session.add(
                Event(
                    ticker=e.ticker,
                    type="earnings",
                    event_date=e.event_date,
                    payload=e.payload,
                )
            )
            saved += 1
    return saved


def ingest(tickers: list[str]) -> dict[str, int]:
    """Fetch & store news + earnings for the given tickers."""
    news_count = 0
    earn_count = 0
    for t in tickers:
        news_count += _persist_news(fetch_news(t))
        earn_count += _persist_earnings(fetch_earnings(t))
    logger.info("Ingested %d news, %d earnings events", news_count, earn_count)
    return {"news": news_count, "earnings": earn_count}


def ingest_portfolio() -> dict[str, int]:
    if not is_available():
        logger.info("Finnhub disabled (no API key); skipping news/earnings ingest")
        return {"news": 0, "earnings": 0}
    return ingest(get_tickers())
