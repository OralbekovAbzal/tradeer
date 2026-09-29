from __future__ import annotations

import pytest

from analysis import journal


def test_open_requires_thesis(db):
    with pytest.raises(ValueError):
        journal.open_entry("AAPL", "  ")
    with pytest.raises(ValueError):
        journal.open_entry("  ", "good thesis")


def test_open_and_close(db):
    eid = journal.open_entry(
        "aapl", "earnings momentum", take_profit_rule="+15%", stop_rule="-7%"
    )
    assert eid >= 1
    journal.close_entry(eid, "win", followed_rules=True, notes="hit target")
    stats = journal.compute_stats()
    assert stats.closed == 1
    assert stats.wins == 1
    assert stats.win_rate == 1.0
    assert stats.rule_follow_rate == 1.0


def test_cannot_double_close(db):
    eid = journal.open_entry("MSFT", "thesis")
    journal.close_entry(eid, "loss", followed_rules=False)
    with pytest.raises(ValueError):
        journal.close_entry(eid, "win", followed_rules=True)


def test_invalid_outcome(db):
    eid = journal.open_entry("MSFT", "thesis")
    with pytest.raises(ValueError):
        journal.close_entry(eid, "moon", followed_rules=True)


def test_rule_following_breakdown(db):
    # Followed rules -> win
    e1 = journal.open_entry("A", "t")
    journal.close_entry(e1, "win", followed_rules=True)
    # Broke rules -> loss
    e2 = journal.open_entry("B", "t")
    journal.close_entry(e2, "loss", followed_rules=False)
    # Broke rules -> win (lucky)
    e3 = journal.open_entry("C", "t")
    journal.close_entry(e3, "win", followed_rules=False)

    stats = journal.compute_stats()
    assert stats.closed == 3
    assert stats.win_rate_when_followed == 1.0
    assert stats.win_rate_when_broke_rules == 0.5
    assert stats.open == 0


def test_open_count(db):
    journal.open_entry("A", "t")
    journal.open_entry("B", "t")
    stats = journal.compute_stats()
    assert stats.total == 2
    assert stats.open == 2
    assert stats.closed == 0
