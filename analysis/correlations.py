"""Correlation & hidden-cluster analysis (spec M5 correlations, Phase 4).

Computes the correlation matrix of daily returns across positions, surfaces
highly correlated pairs, and groups them into clusters (positions that tend to
move together). A cluster carrying a large combined portfolio weight is a hidden
concentration risk even when no single position looks oversized.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from analysis.history import BENCHMARK, daily_returns, load_prices
from analysis.metrics import portfolio_weights

DEFAULT_THRESHOLD = 0.7


@dataclass
class CorrelationPair:
    a: str
    b: str
    corr: float


@dataclass
class Cluster:
    tickers: list[str]
    weight: float          # combined portfolio weight
    avg_corr: float        # average pairwise correlation inside the cluster


@dataclass
class CorrelationReport:
    matrix: pd.DataFrame
    high_pairs: list[CorrelationPair] = field(default_factory=list)
    clusters: list[Cluster] = field(default_factory=list)
    threshold: float = DEFAULT_THRESHOLD
    n_days: int = 0
    note: str | None = None


def correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    if returns.empty or returns.shape[1] < 2:
        return pd.DataFrame()
    return returns.corr()


def high_pairs(matrix: pd.DataFrame, threshold: float) -> list[CorrelationPair]:
    pairs: list[CorrelationPair] = []
    cols = list(matrix.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c = matrix.iloc[i, j]
            if pd.notna(c) and c >= threshold:
                pairs.append(CorrelationPair(cols[i], cols[j], float(c)))
    return sorted(pairs, key=lambda p: p.corr, reverse=True)


def _union_find(tickers: list[str], pairs: list[CorrelationPair]) -> list[list[str]]:
    parent = {t: t for t in tickers}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for p in pairs:
        if p.a in parent and p.b in parent:
            union(p.a, p.b)

    groups: dict[str, list[str]] = {}
    for t in tickers:
        groups.setdefault(find(t), []).append(t)
    # Only clusters of 2+ are meaningful.
    return [sorted(g) for g in groups.values() if len(g) >= 2]


def _avg_pairwise_corr(matrix: pd.DataFrame, tickers: list[str]) -> float:
    vals = []
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            c = matrix.loc[tickers[i], tickers[j]]
            if pd.notna(c):
                vals.append(float(c))
    return sum(vals) / len(vals) if vals else 0.0


def build_clusters(
    matrix: pd.DataFrame,
    weights: dict[str, float],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[Cluster]:
    if matrix.empty:
        return []
    pairs = high_pairs(matrix, threshold)
    groups = _union_find(list(matrix.columns), pairs)
    clusters = [
        Cluster(
            tickers=g,
            weight=sum(weights.get(t, 0.0) for t in g),
            avg_corr=_avg_pairwise_corr(matrix, g),
        )
        for g in groups
    ]
    return sorted(clusters, key=lambda c: c.weight, reverse=True)


def build_report(threshold: float = DEFAULT_THRESHOLD) -> CorrelationReport:
    weights = portfolio_weights()
    tickers = list(weights.keys())
    if len(tickers) < 2:
        return CorrelationReport(
            matrix=pd.DataFrame(), note="Need at least 2 positions."
        )
    # Correlations are between positions only; benchmark excluded.
    prices = load_prices(tickers)
    rets = daily_returns(prices)
    if rets.empty or rets.shape[1] < 2:
        return CorrelationReport(
            matrix=pd.DataFrame(),
            note="No price history cached. Run 'refresh-history' first.",
        )
    matrix = correlation_matrix(rets)
    return CorrelationReport(
        matrix=matrix,
        high_pairs=high_pairs(matrix, threshold),
        clusters=build_clusters(matrix, weights, threshold),
        threshold=threshold,
        n_days=len(rets),
    )
