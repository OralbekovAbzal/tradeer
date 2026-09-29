"""Risk Engine (spec M5, Phase 1).

Pure computation over the current positions plus configurable thresholds.
Phase 1 scope: position concentration, sector concentration, oversized-position
flags, and portfolio drawdown from a peak. Correlations are Phase 4.

Output is FACTS and FLAGS against thresholds — never a buy/sell suggestion
(spec §3, §4).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from config import get_settings
from storage import Position, RiskSnapshot, session_scope


@dataclass
class Concentration:
    ticker: str
    market_value: float
    weight: float  # fraction of portfolio [0, 1]


@dataclass
class SectorConcentration:
    sector: str
    market_value: float
    weight: float


@dataclass
class RiskFlag:
    code: str            # e.g. POSITION_OVERWEIGHT
    severity: str        # info / warning
    subject: str         # ticker or sector name
    message: str
    value: float
    threshold: float


@dataclass
class RiskReport:
    total_value: float
    positions: list[Concentration] = field(default_factory=list)
    sectors: list[SectorConcentration] = field(default_factory=list)
    drawdown: float = 0.0          # fraction below peak [0, 1]
    flags: list[RiskFlag] = field(default_factory=list)


def _position_rows() -> list[Position]:
    with session_scope() as session:
        rows = session.query(Position).all()
        session.expunge_all()
        return rows


def _market_value(p: Position) -> float:
    if p.market_value is not None:
        return float(p.market_value)
    # Fall back to avg_price if current price not yet refreshed.
    price = p.current_price if p.current_price is not None else p.avg_price
    return float(price) * float(p.qty)


def compute_drawdown(equity_curve: list[float]) -> float:
    """Max-to-current drawdown as a positive fraction.

    Given a series of portfolio values, returns (peak - last) / peak using the
    running peak up to the final point. 0.0 if empty or never below peak.
    """
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    for v in equity_curve:
        peak = max(peak, v)
    if peak <= 0:
        return 0.0
    last = equity_curve[-1]
    return max(0.0, (peak - last) / peak)


def build_report(equity_curve: list[float] | None = None) -> RiskReport:
    """Compute the full risk report from current positions and thresholds.

    equity_curve: optional series of historical total portfolio values used for
    drawdown. If omitted, drawdown is 0 (no history available in Phase 1 yet).
    """
    settings = get_settings()
    positions = _position_rows()

    values = {p.ticker: _market_value(p) for p in positions}
    total = sum(values.values())

    report = RiskReport(total_value=total)
    if total <= 0:
        return report

    # Position concentration
    for p in positions:
        mv = values[p.ticker]
        weight = mv / total
        report.positions.append(Concentration(p.ticker, mv, weight))
        if weight > settings.max_position_pct:
            report.flags.append(
                RiskFlag(
                    code="POSITION_OVERWEIGHT",
                    severity="warning",
                    subject=p.ticker,
                    message=(
                        f"{p.ticker} is {weight:.1%} of the portfolio, "
                        f"above the {settings.max_position_pct:.0%} limit."
                    ),
                    value=weight,
                    threshold=settings.max_position_pct,
                )
            )
    report.positions.sort(key=lambda c: c.weight, reverse=True)

    # Sector concentration
    sector_mv: dict[str, float] = {}
    for p in positions:
        sector = p.sector or "Unknown"
        sector_mv[sector] = sector_mv.get(sector, 0.0) + values[p.ticker]
    for sector, mv in sector_mv.items():
        weight = mv / total
        report.sectors.append(SectorConcentration(sector, mv, weight))
        if sector != "Unknown" and weight > settings.max_sector_pct:
            report.flags.append(
                RiskFlag(
                    code="SECTOR_OVERWEIGHT",
                    severity="warning",
                    subject=sector,
                    message=(
                        f"Sector '{sector}' is {weight:.1%} of the portfolio, "
                        f"above the {settings.max_sector_pct:.0%} limit."
                    ),
                    value=weight,
                    threshold=settings.max_sector_pct,
                )
            )
    report.sectors.sort(key=lambda s: s.weight, reverse=True)

    # Drawdown
    if equity_curve:
        dd = compute_drawdown(equity_curve)
        report.drawdown = dd
        if dd > settings.max_drawdown_pct:
            report.flags.append(
                RiskFlag(
                    code="DRAWDOWN_EXCEEDED",
                    severity="warning",
                    subject="portfolio",
                    message=(
                        f"Drawdown is {dd:.1%}, beyond the "
                        f"{settings.max_drawdown_pct:.0%} limit."
                    ),
                    value=dd,
                    threshold=settings.max_drawdown_pct,
                )
            )

    return report


def save_snapshot(report: RiskReport) -> int:
    """Persist a risk report to risk_snapshots. Returns the snapshot id."""
    with session_scope() as session:
        snap = RiskSnapshot(
            taken_at=datetime.now(timezone.utc),
            concentration_json=json.dumps(
                {
                    "positions": [asdict(c) for c in report.positions],
                    "sectors": [asdict(s) for s in report.sectors],
                }
            ),
            drawdown=report.drawdown,
            flags_json=json.dumps([asdict(f) for f in report.flags]),
        )
        session.add(snap)
        session.flush()
        return snap.id
