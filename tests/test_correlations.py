from __future__ import annotations

import numpy as np
import pandas as pd

from analysis import correlations


def _returns():
    rng = np.random.default_rng(42)
    base = rng.normal(0, 0.01, 200)
    a = base + rng.normal(0, 0.0005, 200)       # A and B nearly identical
    b = base + rng.normal(0, 0.0005, 200)
    c = rng.normal(0, 0.01, 200)                # C independent
    return pd.DataFrame({"A": a, "B": b, "C": c})


def test_correlation_matrix_shape():
    m = correlations.correlation_matrix(_returns())
    assert list(m.columns) == ["A", "B", "C"]
    assert abs(m.loc["A", "A"] - 1.0) < 1e-9


def test_correlation_matrix_empty_single_column():
    m = correlations.correlation_matrix(pd.DataFrame({"A": [0.1, 0.2]}))
    assert m.empty


def test_high_pairs_finds_correlated():
    m = correlations.correlation_matrix(_returns())
    pairs = correlations.high_pairs(m, threshold=0.7)
    found = {(p.a, p.b) for p in pairs}
    assert ("A", "B") in found
    assert all(p.corr >= 0.7 for p in pairs)


def test_union_find_groups_clusters():
    pairs = [correlations.CorrelationPair("A", "B", 0.9)]
    groups = correlations._union_find(["A", "B", "C"], pairs)
    assert ["A", "B"] in groups
    # C is alone, so excluded (clusters need 2+).
    assert all("C" not in g for g in groups)


def test_build_clusters_weight_sum():
    m = correlations.correlation_matrix(_returns())
    weights = {"A": 0.3, "B": 0.3, "C": 0.4}
    clusters = correlations.build_clusters(m, weights, threshold=0.7)
    ab = [c for c in clusters if set(c.tickers) == {"A", "B"}]
    assert ab
    assert abs(ab[0].weight - 0.6) < 1e-9


def test_build_report_needs_two_positions(db):
    rep = correlations.build_report()
    assert rep.note is not None
