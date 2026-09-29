from __future__ import annotations

import json

from connectors import news


def test_normalize_news_basic():
    raw = [
        {
            "headline": "Acme beats estimates",
            "url": "http://x/1",
            "source": "Reuters",
            "datetime": 1_700_000_000,
        },
        {"headline": "   ", "datetime": 1_700_000_500},  # empty -> skipped
        {"summary": "no headline key"},  # skipped
    ]
    out = news.normalize_news(raw, "ACME")
    assert len(out) == 1
    assert out[0].ticker == "ACME"
    assert out[0].headline == "Acme beats estimates"
    assert out[0].source == "Reuters"
    assert out[0].published_at is not None


def test_normalize_news_empty():
    assert news.normalize_news(None, "X") == []
    assert news.normalize_news([], "X") == []


def test_normalize_earnings():
    raw = {
        "earningsCalendar": [
            {
                "symbol": "aapl",
                "date": "2026-06-01",
                "epsEstimate": 1.2,
                "revenueEstimate": 1000,
                "hour": "amc",
            },
            {"symbol": "", "date": "2026-06-02"},  # skipped
        ]
    }
    out = news.normalize_earnings(raw)
    assert len(out) == 1
    e = out[0]
    assert e.ticker == "AAPL"
    assert e.event_date is not None and e.event_date.year == 2026
    assert json.loads(e.payload)["epsEstimate"] == 1.2


def test_is_available_without_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert news.is_available() is False


def test_persist_news_dedup(db):
    items = news.normalize_news(
        [{"headline": "Same", "datetime": 1_700_000_000}], "ACME"
    )
    assert news._persist_news(items) == 1
    assert news._persist_news(items) == 0  # duplicate skipped
