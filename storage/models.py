"""SQLAlchemy ORM models (spec §10).

The full schema is defined now so later phases can populate tables without
migrations. Phase 1 actively uses: positions, trades, journal_entries,
risk_snapshots. The rest (news, events, insider_filings, alerts_log) are
created empty and filled in Phases 2-4.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    qty: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    sector: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(8))  # buy / sell
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    executed_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # api / manual


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    thesis: Mapped[str] = mapped_column(Text)
    entry_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    take_profit_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)  # win/loss/flat
    followed_rules: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class News(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    headline: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    llm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    type: Mapped[str] = mapped_column(String(24))  # earnings/dividend/insider
    event_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string


class InsiderFiling(Base):
    __tablename__ = "insider_filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    insider_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    transaction_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_price_ticker_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    close: Mapped[float] = mapped_column(Float)


class RiskSnapshot(Base):
    __tablename__ = "risk_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    concentration_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    flags_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class AlertLog(Base):
    __tablename__ = "alerts_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(40))
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    # Stable key used to avoid re-sending the same alert (e.g. risk:CODE:SUBJ).
    dedup_key: Mapped[str | None] = mapped_column(String(200), index=True, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    channel: Mapped[str | None] = mapped_column(String(24), nullable=True)
