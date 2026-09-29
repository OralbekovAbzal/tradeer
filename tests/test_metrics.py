from __future__ import annotations

import numpy as np
import pandas as pd

from analysis import metrics


def test_annualized_volatility_zero_for_constant():
    s = pd.Series([0.0, 0.0, 0.0])
    assert metrics.annualized_volatility(s) == 0.0


def test_annualized_volatility_scales_with_sqrt_periods():
    s = pd.Series([0.01, -0.01, 0.02, -0.02, 0.0])
    daily = s.std(ddof=1)
    assert abs(metrics.annualized_volatility(s, periods=252) - daily * (252 ** 0.5)) < 1e-9


def test_beta_of_asset_vs_itself_is_one():
    rng = np.random.default_rng(0)
    m = pd.Series(rng.normal(0, 0.01, 100))
    assert abs(metrics.beta(m, m) - 1.0) < 1e-9


def test_beta_zero_market_variance():
    a = pd.Series([0.01, 0.02, -0.01])
    m = pd.Series([0.0, 0.0, 0.0])
    assert metrics.beta(a, m) == 0.0


def test_historical_var_positive_loss():
    s = pd.Series([-0.05, -0.02, 0.01, 0.03, 0.04])
    var = metrics.historical_var(s, confidence=0.95)
    assert var >= 0.0


def test_parametric_var_nonnegative():
    s = pd.Series([0.01, -0.01, 0.02, -0.02, 0.0])
    assert metrics.parametric_var(s, 0.95) >= 0.0


def test_max_drawdown():
    equity = pd.Series([1.0, 1.2, 0.9, 1.1])
    # peak 1.2 -> trough 0.9 = 25%
    assert abs(metrics.max_drawdown(equity) - 0.25) < 1e-9


def test_sharpe_zero_when_no_variance():
    s = pd.Series([0.01, 0.01, 0.01])
    assert metrics.sharpe(s) == 0.0


def test_portfolio_returns_weighted():
    rets = pd.DataFrame({"A": [0.10, 0.0], "B": [0.0, 0.20]})
    out = metrics.portfolio_returns(rets, {"A": 0.5, "B": 0.5})
    assert abs(out.iloc[0] - 0.05) < 1e-9
    assert abs(out.iloc[1] - 0.10) < 1e-9


def test_portfolio_returns_empty_when_no_overlap():
    rets = pd.DataFrame({"A": [0.1]})
    out = metrics.portfolio_returns(rets, {"Z": 1.0})
    assert out.empty


def test_build_metrics_empty_portfolio(db):
    m = metrics.build_metrics()
    assert m.total_value == 0.0
    assert m.note is not None
