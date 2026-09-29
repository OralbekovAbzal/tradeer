from __future__ import annotations

from datetime import datetime, timezone

from analysis import scenarios
from storage import Position, session_scope


def _add(ticker, qty, price, sector):
    with session_scope() as session:
        session.add(
            Position(
                ticker=ticker,
                qty=qty,
                avg_price=price,
                current_price=price,
                market_value=price * qty,
                sector=sector,
                updated_at=datetime.now(timezone.utc),
            )
        )


def test_market_shock_scales_by_beta():
    r = scenarios.market_shock(beta=1.5, total_value=1000.0, shock=-0.10)
    assert abs(r.pct_impact - (-0.15)) < 1e-9
    assert abs(r.value_impact - (-150.0)) < 1e-9


def test_sector_shock_scales_by_weight():
    r = scenarios.sector_shock("Technology", weight=0.5, total_value=1000.0, shock=-0.20)
    assert abs(r.pct_impact - (-0.10)) < 1e-9
    assert abs(r.value_impact - (-100.0)) < 1e-9


def test_rate_shock_uses_sensitivity():
    sweights = {"Technology": 1.0}
    r = scenarios.rate_shock(sweights, total_value=1000.0, bps=100)
    # Technology sensitivity is -0.05 at +100bps.
    assert abs(r.pct_impact - (-0.05)) < 1e-9


def test_sector_weights_from_db(db):
    _add("AAA", 50, 1.0, "Technology")
    _add("BBB", 50, 1.0, "Energy")
    w = scenarios.sector_weights()
    assert abs(w["Technology"] - 0.5) < 1e-9
    assert abs(w["Energy"] - 0.5) < 1e-9


def test_build_report_empty(db):
    rep = scenarios.build_report()
    assert rep.total_value == 0.0
    assert rep.note == "No positions."


def test_build_report_with_positions(db):
    _add("AAA", 50, 1.0, "Technology")
    _add("BBB", 50, 1.0, "Energy")
    rep = scenarios.build_report(portfolio_beta=1.0)
    names = {r.name for r in rep.results}
    assert any("Market" in n for n in names)
    assert any("Rates" in n for n in names)
