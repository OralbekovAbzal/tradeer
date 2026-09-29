from __future__ import annotations

from datetime import datetime, timedelta, timezone

from alerts import engine
from storage import Event, News, Position, session_scope


def _now():
    return datetime.now(timezone.utc)


def _add_overweight_position():
    with session_scope() as session:
        session.add(
            Position(
                ticker="AAA",
                qty=100,
                avg_price=1.0,
                current_price=1.0,
                market_value=100.0,
                sector="Tech",
                updated_at=_now(),
            )
        )


def test_risk_candidate(db):
    _add_overweight_position()  # single position = 100% -> overweight
    cands = engine.build_candidates()
    assert any(c.type == "risk" for c in cands)


def test_earnings_candidate_within_window(db):
    soon = _now() + timedelta(days=2)
    far = _now() + timedelta(days=60)
    with session_scope() as session:
        session.add(Event(ticker="AAA", type="earnings", event_date=soon))
        session.add(Event(ticker="BBB", type="earnings", event_date=far))
    cands = engine.build_candidates()
    earnings = [c for c in cands if c.type == "earnings"]
    assert any(c.ticker == "AAA" for c in earnings)
    assert not any(c.ticker == "BBB" for c in earnings)


def test_news_candidate_recent_only(db):
    recent = _now() - timedelta(hours=2)
    old = _now() - timedelta(days=5)
    with session_scope() as session:
        session.add(News(ticker="AAA", headline="fresh", published_at=recent))
        session.add(News(ticker="AAA", headline="stale", published_at=old))
    cands = engine.build_candidates()
    headlines = [c.message for c in cands if c.type == "news"]
    assert any("fresh" in h for h in headlines)
    assert not any("stale" in h for h in headlines)


def test_dispatch_dedup(db):
    _add_overweight_position()
    first = engine.run()
    assert first >= 1
    second = engine.run()  # same conditions -> nothing new
    assert second == 0
