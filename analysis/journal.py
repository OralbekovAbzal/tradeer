"""Trading Journal (spec M6, Phase 1).

Before entering a trade the user records a thesis: why, profit-taking rule,
and the condition that means "I was wrong, exit". After closing, the entry is
marked with an outcome and whether the user followed their own rules. The
discipline statistics summarize win rate, average P&L, and rule-following.

Auto-matching to broker trade history is Phase 3; Phase 1 records outcomes
manually.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from storage import JournalEntry, session_scope

VALID_OUTCOMES = {"win", "loss", "flat"}


def open_entry(
    ticker: str,
    thesis: str,
    entry_condition: str | None = None,
    take_profit_rule: str | None = None,
    stop_rule: str | None = None,
    notes: str | None = None,
) -> int:
    """Record a pre-entry thesis. Returns the new entry id."""
    if not ticker.strip():
        raise ValueError("ticker is required")
    if not thesis.strip():
        raise ValueError("thesis is required (record why you are entering)")
    with session_scope() as session:
        entry = JournalEntry(
            ticker=ticker.strip().upper(),
            thesis=thesis.strip(),
            entry_condition=entry_condition,
            take_profit_rule=take_profit_rule,
            stop_rule=stop_rule,
            notes=notes,
            opened_at=datetime.now(timezone.utc),
        )
        session.add(entry)
        session.flush()
        return entry.id


def close_entry(
    entry_id: int,
    outcome: str,
    followed_rules: bool,
    notes: str | None = None,
) -> None:
    """Close an open journal entry with its result."""
    outcome = outcome.strip().lower()
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(VALID_OUTCOMES)}")
    with session_scope() as session:
        entry = session.get(JournalEntry, entry_id)
        if entry is None:
            raise ValueError(f"journal entry {entry_id} not found")
        if entry.closed_at is not None:
            raise ValueError(f"journal entry {entry_id} is already closed")
        entry.closed_at = datetime.now(timezone.utc)
        entry.outcome = outcome
        entry.followed_rules = followed_rules
        if notes:
            entry.notes = (entry.notes + "\n" if entry.notes else "") + notes


@dataclass
class JournalStats:
    total: int
    open: int
    closed: int
    wins: int
    losses: int
    flat: int
    win_rate: float            # wins / closed
    rule_follow_rate: float    # followed_rules True / closed
    win_rate_when_followed: float
    win_rate_when_broke_rules: float


def compute_stats() -> JournalStats:
    """Discipline statistics across all journal entries."""
    with session_scope() as session:
        entries = session.query(JournalEntry).all()
        session.expunge_all()

    total = len(entries)
    closed = [e for e in entries if e.closed_at is not None]
    n_closed = len(closed)
    wins = sum(1 for e in closed if e.outcome == "win")
    losses = sum(1 for e in closed if e.outcome == "loss")
    flat = sum(1 for e in closed if e.outcome == "flat")
    followed = [e for e in closed if e.followed_rules]
    broke = [e for e in closed if e.followed_rules is False]

    def rate(num: int, den: int) -> float:
        return num / den if den else 0.0

    return JournalStats(
        total=total,
        open=total - n_closed,
        closed=n_closed,
        wins=wins,
        losses=losses,
        flat=flat,
        win_rate=rate(wins, n_closed),
        rule_follow_rate=rate(len(followed), n_closed),
        win_rate_when_followed=rate(
            sum(1 for e in followed if e.outcome == "win"), len(followed)
        ),
        win_rate_when_broke_rules=rate(
            sum(1 for e in broke if e.outcome == "win"), len(broke)
        ),
    )
