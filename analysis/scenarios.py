"""Scenario / stress-test engine (Phase 4).

Estimates portfolio impact under hypothetical shocks:
  - broad market moves, scaled by the portfolio's beta,
  - sector shocks, scaled by the portfolio's exposure to that sector,
  - a stylized rate move applied to rate-sensitive sectors.

These are first-order approximations meant to size risk, not precise forecasts.
They use realized beta (from metrics) and current sector weights.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from analysis import metrics
from storage import Position, session_scope

# Stylized 1-day sector sensitivity to a +1% rate move (heuristic, not a model).
RATE_SENSITIVITY = {
    "Technology": -0.05,
    "Real Estate": -0.06,
    "Utilities": -0.04,
    "Communication Services": -0.03,
    "Consumer Cyclical": -0.03,
}


@dataclass
class ScenarioResult:
    name: str
    description: str
    pct_impact: float       # fraction change to portfolio value
    value_impact: float     # absolute change in currency


@dataclass
class ScenarioReport:
    total_value: float
    portfolio_beta: float
    results: list[ScenarioResult] = field(default_factory=list)
    note: str | None = None


def sector_weights() -> dict[str, float]:
    with session_scope() as session:
        rows = session.query(Position).all()
        session.expunge_all()
    values: dict[str, float] = {}
    total = 0.0
    for p in rows:
        mv = p.market_value
        if mv is None:
            price = p.current_price if p.current_price is not None else p.avg_price
            mv = float(price) * float(p.qty)
        sector = p.sector or "Unknown"
        values[sector] = values.get(sector, 0.0) + float(mv)
        total += float(mv)
    if total <= 0:
        return {}
    return {s: v / total for s, v in values.items()}


def market_shock(beta: float, total_value: float, shock: float) -> ScenarioResult:
    pct = beta * shock
    return ScenarioResult(
        name=f"Market {shock:+.0%}",
        description=f"Broad market moves {shock:+.0%}; scaled by portfolio beta {beta:.2f}.",
        pct_impact=pct,
        value_impact=pct * total_value,
    )


def sector_shock(
    sector: str, weight: float, total_value: float, shock: float
) -> ScenarioResult:
    pct = weight * shock
    return ScenarioResult(
        name=f"{sector} {shock:+.0%}",
        description=(
            f"Sector '{sector}' moves {shock:+.0%}; portfolio exposure {weight:.0%}."
        ),
        pct_impact=pct,
        value_impact=pct * total_value,
    )


def rate_shock(
    sweights: dict[str, float], total_value: float, bps: int = 100
) -> ScenarioResult:
    scale = bps / 100.0
    pct = sum(
        sweights.get(sec, 0.0) * sens * scale
        for sec, sens in RATE_SENSITIVITY.items()
    )
    return ScenarioResult(
        name=f"Rates +{bps}bps",
        description=(
            f"+{bps}bps rate move applied to rate-sensitive sectors (heuristic)."
        ),
        pct_impact=pct,
        value_impact=pct * total_value,
    )


def build_report(portfolio_beta: float | None = None) -> ScenarioReport:
    m = metrics.build_metrics()
    total_value = m.total_value
    if total_value <= 0:
        return ScenarioReport(0.0, 0.0, note="No positions.")
    beta = portfolio_beta if portfolio_beta is not None else m.beta
    sweights = sector_weights()

    results = [
        market_shock(beta, total_value, -0.10),
        market_shock(beta, total_value, -0.20),
        market_shock(beta, total_value, +0.10),
    ]
    # Shock the largest sector exposure (excluding Unknown).
    ranked = sorted(
        ((s, w) for s, w in sweights.items() if s != "Unknown"),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if ranked:
        top_sector, top_w = ranked[0]
        results.append(sector_shock(top_sector, top_w, total_value, -0.15))
    results.append(rate_shock(sweights, total_value, 100))

    note = None if m.n_days else "Beta is 0 (no history cached); market scenarios approximate."
    return ScenarioReport(
        total_value=total_value, portfolio_beta=beta, results=results, note=note
    )
