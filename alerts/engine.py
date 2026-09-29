"""Alert rules engine (spec M9, Phase 2).

Builds alert candidates from current state and dispatches the new ones to
Telegram, logging every alert to the database for audit and deduplication.

Candidates come from three sources:
  - risk thresholds breached (concentration / sector / drawdown),
  - earnings dates approaching within the configured window,
  - company news published in the last 24 hours.

Deduplication uses a stable `dedup_key` so the same condition is not pushed on
every scheduler tick. Alerts are always recorded in alerts_log even when
Telegram is not configured (channel="log"), so nothing is silently lost.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import get_settings
from analysis import risk
from alerts import telegram_bot
from storage import AlertLog, Event, News, session_scope

logger = logging.getLogger(__name__)


@dataclass
class AlertCandidate:
    type: str       # risk / earnings / news
    ticker: str | None
    message: str
    dedup_key: str


def _risk_candidates() -> list[AlertCandidate]:
    report = risk.build_report()
    out = []
    for f in report.flags:
        if f.severity != "warning":
            continue
        out.append(
            AlertCandidate(
                type="risk",
                ticker=f.subject if f.code == "POSITION_OVERWEIGHT" else None,
                message=f"⚠️ Риск: {f.message}",
                dedup_key=f"risk:{f.code}:{f.subject}",
            )
        )
    return out


def _earnings_candidates(now: datetime) -> list[AlertCandidate]:
    settings = get_settings()
    horizon = now + timedelta(days=settings.earnings_alert_days)
    out = []
    with session_scope() as session:
        rows = (
            session.query(Event)
            .filter(
                Event.type == "earnings",
                Event.event_date.isnot(None),
                Event.event_date >= now,
                Event.event_date <= horizon,
            )
            .all()
        )
        session.expunge_all()
    for e in rows:
        date_str = e.event_date.date().isoformat() if e.event_date else "?"
        out.append(
            AlertCandidate(
                type="earnings",
                ticker=e.ticker,
                message=f"📅 Отчёт {e.ticker} ожидается {date_str}",
                dedup_key=f"earnings:{e.ticker}:{date_str}",
            )
        )
    return out


def _news_candidates(now: datetime) -> list[AlertCandidate]:
    since = now - timedelta(days=1)
    out = []
    with session_scope() as session:
        rows = (
            session.query(News)
            .filter(News.published_at.isnot(None), News.published_at >= since)
            .all()
        )
        session.expunge_all()
    for n in rows:
        out.append(
            AlertCandidate(
                type="news",
                ticker=n.ticker,
                message=f"📰 {n.ticker}: {n.headline}",
                dedup_key=f"news:{n.ticker}:{n.headline}",
            )
        )
    return out


def build_candidates(now: datetime | None = None) -> list[AlertCandidate]:
    now = now or datetime.now(timezone.utc)
    return _risk_candidates() + _earnings_candidates(now) + _news_candidates(now)


def _already_sent(session, dedup_key: str) -> bool:
    return (
        session.query(AlertLog.id)
        .filter(AlertLog.dedup_key == dedup_key)
        .first()
        is not None
    )


def dispatch(candidates: list[AlertCandidate]) -> int:
    """Send and log new candidates. Returns number of new alerts dispatched."""
    sent = 0
    with session_scope() as session:
        for c in candidates:
            if _already_sent(session, c.dedup_key):
                continue
            pushed = telegram_bot.send(c.message)
            session.add(
                AlertLog(
                    type=c.type,
                    ticker=c.ticker,
                    message=c.message,
                    dedup_key=c.dedup_key,
                    channel="telegram" if pushed else "log",
                )
            )
            sent += 1
    logger.info("Dispatched %d new alerts", sent)
    return sent


def run() -> int:
    return dispatch(build_candidates())
