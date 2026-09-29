"""Manual / CSV position import (spec Phase 1).

This is the broker-independent path: the user exports or types positions into
a CSV and the tool ingests them. When the broker API arrives (Phase 3) it will
populate the same `positions` table.

Expected CSV columns (header row required):
    ticker, qty, avg_price[, sector]

`current_price` and `market_value` are filled by refresh_prices() using the
market connector; sector is filled from CSV or looked up if missing.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete

from connectors import market
from storage import Position, session_scope

logger = logging.getLogger(__name__)


@dataclass
class ParsedPosition:
    ticker: str
    qty: float
    avg_price: float
    sector: str | None = None


def get_tickers() -> list[str]:
    """Distinct tickers currently held, used by the information-layer ingests."""
    with session_scope() as session:
        rows = session.query(Position.ticker).distinct().all()
    return [r[0] for r in rows]


def parse_csv(path: str | Path) -> list[ParsedPosition]:
    """Parse a positions CSV into validated rows. Raises on malformed input."""
    path = Path(path)
    rows: list[ParsedPosition] = []
    # utf-8-sig strips the BOM that Excel's "CSV UTF-8" export prepends;
    # without it the first header reads "﻿ticker" and import fails.
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header row")
        required = {"ticker", "qty", "avg_price"}
        header = {h.strip().lower() for h in reader.fieldnames}
        missing = required - header
        if missing:
            raise ValueError(f"CSV missing required columns: {sorted(missing)}")
        for i, raw in enumerate(reader, start=2):
            norm = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
            ticker = norm.get("ticker", "").upper()
            if not ticker:
                logger.warning("Skipping row %d: empty ticker", i)
                continue
            try:
                qty = float(norm["qty"])
                avg_price = float(norm["avg_price"])
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Row {i} ({ticker}): invalid qty/avg_price: {exc}")
            sector = norm.get("sector") or None
            rows.append(ParsedPosition(ticker, qty, avg_price, sector))
    return rows


def import_csv(path: str | Path, replace: bool = True) -> int:
    """Load a CSV into the positions table. Returns number of rows imported.

    replace=True clears existing positions first (full snapshot semantics).
    """
    parsed = parse_csv(path)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        if replace:
            session.execute(delete(Position))
        for p in parsed:
            session.add(
                Position(
                    ticker=p.ticker,
                    qty=p.qty,
                    avg_price=p.avg_price,
                    sector=p.sector,
                    updated_at=now,
                )
            )
    logger.info("Imported %d positions from %s", len(parsed), path)
    return len(parsed)


def refresh_prices(lookup_sector: bool = False) -> int:
    """Update current_price, market_value (and optionally sector) for all
    positions using the market connector. Returns count updated.

    Degrades gracefully: positions whose price can't be fetched keep their
    last known values.
    """
    now = datetime.now(timezone.utc)
    updated = 0
    with session_scope() as session:
        positions = session.query(Position).all()
        for pos in positions:
            price = market.get_price(pos.ticker)
            if price is not None:
                pos.current_price = price
                pos.market_value = price * pos.qty
                pos.updated_at = now
                updated += 1
            if lookup_sector and not pos.sector:
                pos.sector = market.get_sector(pos.ticker)
    logger.info("Refreshed prices for %d/%d positions", updated, len(positions))
    return updated
