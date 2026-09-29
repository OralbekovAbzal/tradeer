"""Advanced risk metrics (spec M5 extension, Phase 4).

Pure numeric functions over return series plus an orchestrator that pulls the
cached price history and current portfolio weights to produce per-position and
portfolio-level metrics: volatility, beta vs the market, Value-at-Risk
(historical & parametric), max drawdown, Sharpe and Sortino.

All outputs are facts about realized risk — not forecasts or recommendations.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from analysis.history import BENCHMARK, daily_returns, load_prices
from storage import Position, session_scope

TRADING_DAYS = 252


# --- Pure functions -------------------------------------------------------

def annualized_volatility(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    if returns.empty:
        return 0.0
    return float(returns.std(ddof=1) * math.sqrt(periods))


def annualized_return(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    if returns.empty:
        return 0.0
    return float(returns.mean() * periods)


def beta(asset: pd.Series, market: pd.Series) -> float:
    """Beta of an asset vs the market (covariance / market variance)."""
    df = pd.concat([asset, market], axis=1, join="inner").dropna()
    if len(df) < 2:
        return 0.0
    a, m = df.iloc[:, 0], df.iloc[:, 1]
    var = m.var(ddof=1)
    if var == 0:
        return 0.0
    return float(a.cov(m) / var)


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Historical Value-at-Risk as a positive fraction of one-day loss."""
    if returns.empty:
        return 0.0
    q = returns.quantile(1 - confidence)
    return float(max(0.0, -q))


def parametric_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Gaussian VaR using mean/std; positive fraction of one-day loss."""
    if returns.empty:
        return 0.0
    # z-scores for common confidences without scipy dependency.
    z = {0.90: 1.2816, 0.95: 1.6449, 0.975: 1.9600, 0.99: 2.3263}.get(
        round(confidence, 3), 1.6449
    )
    mu, sigma = returns.mean(), returns.std(ddof=1)
    return float(max(0.0, z * sigma - mu))


def max_drawdown(equity: pd.Series) -> float:
    """Worst peak-to-trough decline over the series, as a positive fraction."""
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    dd = equity / running_max - 1.0
    return float(-dd.min())


def sharpe(returns: pd.Series, rf: float = 0.0, periods: int = TRADING_DAYS) -> float:
    if returns.empty or returns.std(ddof=1) == 0:
        return 0.0
    excess = returns - rf / periods
    return float(excess.mean() / returns.std(ddof=1) * math.sqrt(periods))


def sortino(returns: pd.Series, rf: float = 0.0, periods: int = TRADING_DAYS) -> float:
    if returns.empty:
        return 0.0
    excess = returns - rf / periods
    downside = excess[excess < 0]
    dstd = downside.std(ddof=1)
    if dstd == 0 or math.isnan(dstd):
        return 0.0
    return float(excess.mean() / dstd * math.sqrt(periods))


def portfolio_returns(returns: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Weighted portfolio return series from per-asset returns."""
    cols = [c for c in returns.columns if c in weights]
    if not cols:
        return pd.Series(dtype=float)
    w = pd.Series({c: weights[c] for c in cols})
    total = w.sum()
    if total == 0:
        return pd.Series(dtype=float)
    w = w / total
    return (returns[cols] * w).sum(axis=1)


# --- Orchestration --------------------------------------------------------

@dataclass
class PositionMetrics:
    ticker: str
    weight: float
    annual_vol: float
    beta: float


@dataclass
class PortfolioMetrics:
    total_value: float
    annual_return: float
    annual_vol: float
    beta: float
    var_95_hist: float
    var_95_param: float
    max_drawdown: float
    sharpe: float
    sortino: float
    benchmark: str
    n_days: int
    positions: list[PositionMetrics] = field(default_factory=list)
    note: str | None = None


def portfolio_weights() -> dict[str, float]:
    """Current weights from position market values (fallback to avg_price)."""
    with session_scope() as session:
        rows = session.query(Position).all()
        session.expunge_all()
    values = {}
    for p in rows:
        mv = p.market_value
        if mv is None:
            price = p.current_price if p.current_price is not None else p.avg_price
            mv = float(price) * float(p.qty)
        values[p.ticker] = float(mv)
    total = sum(values.values())
    if total <= 0:
        return {}
    return {t: v / total for t, v in values.items()}


def build_metrics() -> PortfolioMetrics:
    """Compute full metrics from cached history and current weights."""
    weights = portfolio_weights()
    total_value = _total_value()
    if not weights:
        return _empty(total_value, "No positions.")

    tickers = list(weights.keys())
    prices = load_prices(tickers + [BENCHMARK])
    if prices.empty or BENCHMARK not in prices.columns:
        return _empty(
            total_value,
            "No price history cached. Run 'refresh-history' first.",
        )

    rets = daily_returns(prices)
    if rets.empty or len(rets) < 5:
        return _empty(total_value, "Not enough history for metrics.")

    market_ret = rets[BENCHMARK]
    port_ret = portfolio_returns(rets, weights)
    equity = (1 + port_ret).cumprod()

    pos_metrics = [
        PositionMetrics(
            ticker=t,
            weight=weights[t],
            annual_vol=annualized_volatility(rets[t]) if t in rets else 0.0,
            beta=beta(rets[t], market_ret) if t in rets else 0.0,
        )
        for t in tickers
    ]

    return PortfolioMetrics(
        total_value=total_value,
        annual_return=annualized_return(port_ret),
        annual_vol=annualized_volatility(port_ret),
        beta=beta(port_ret, market_ret),
        var_95_hist=historical_var(port_ret, 0.95),
        var_95_param=parametric_var(port_ret, 0.95),
        max_drawdown=max_drawdown(equity),
        sharpe=sharpe(port_ret),
        sortino=sortino(port_ret),
        benchmark=BENCHMARK,
        n_days=len(rets),
        positions=sorted(pos_metrics, key=lambda p: p.weight, reverse=True),
    )


def _total_value() -> float:
    with session_scope() as session:
        rows = session.query(Position).all()
        session.expunge_all()
    total = 0.0
    for p in rows:
        mv = p.market_value
        if mv is None:
            price = p.current_price if p.current_price is not None else p.avg_price
            mv = float(price) * float(p.qty)
        total += float(mv)
    return total


def _empty(total_value: float, note: str) -> PortfolioMetrics:
    return PortfolioMetrics(
        total_value=total_value,
        annual_return=0.0,
        annual_vol=0.0,
        beta=0.0,
        var_95_hist=0.0,
        var_95_param=0.0,
        max_drawdown=0.0,
        sharpe=0.0,
        sortino=0.0,
        benchmark=BENCHMARK,
        n_days=0,
        note=note,
    )
