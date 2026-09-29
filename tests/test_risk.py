from __future__ import annotations

from datetime import datetime, timezone

from analysis import risk
from storage import Position, session_scope


def _add_position(ticker, qty, avg_price, current_price, sector):
    with session_scope() as session:
        session.add(
            Position(
                ticker=ticker,
                qty=qty,
                avg_price=avg_price,
                current_price=current_price,
                market_value=current_price * qty,
                sector=sector,
                updated_at=datetime.now(timezone.utc),
            )
        )


def test_compute_drawdown():
    assert risk.compute_drawdown([]) == 0.0
    assert risk.compute_drawdown([100, 110, 121]) == 0.0
    # peak 120, last 90 -> 25%
    assert abs(risk.compute_drawdown([100, 120, 90]) - 0.25) < 1e-9


def test_position_overweight_flag(db):
    _add_position("AAA", 100, 1.0, 1.0, "Tech")   # 100
    _add_position("BBB", 10, 1.0, 1.0, "Energy")  # 10
    report = risk.build_report()
    assert abs(report.total_value - 110.0) < 1e-9
    codes = {f.code for f in report.flags}
    assert "POSITION_OVERWEIGHT" in codes  # AAA ~ 90% > 25%
    top = report.positions[0]
    assert top.ticker == "AAA"
    assert top.weight > 0.8


def test_sector_overweight_flag(db):
    _add_position("AAA", 50, 1.0, 1.0, "Tech")
    _add_position("BBB", 50, 1.0, 1.0, "Tech")
    _add_position("CCC", 20, 1.0, 1.0, "Energy")
    report = risk.build_report()
    codes = {f.code for f in report.flags}
    assert "SECTOR_OVERWEIGHT" in codes  # Tech ~ 83% > 40%


def test_no_flags_when_balanced(db):
    for t in ["A", "B", "C", "D", "E"]:
        _add_position(t, 20, 1.0, 1.0, t)  # each 20%, distinct sectors
    report = risk.build_report()
    assert report.flags == []


def test_drawdown_flag(db):
    _add_position("AAA", 100, 1.0, 1.0, "Tech")
    report = risk.build_report(equity_curve=[1000, 1200, 800])  # 33% dd
    codes = {f.code for f in report.flags}
    assert "DRAWDOWN_EXCEEDED" in codes


def test_empty_portfolio(db):
    report = risk.build_report()
    assert report.total_value == 0.0
    assert report.flags == []


def test_save_snapshot(db):
    _add_position("AAA", 100, 1.0, 1.0, "Tech")
    report = risk.build_report()
    snap_id = risk.save_snapshot(report)
    assert snap_id >= 1
