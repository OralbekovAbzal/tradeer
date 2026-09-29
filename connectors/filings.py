"""Insider filings — SEC EDGAR Form 4 (spec M3, Phase 2).

Pulls publicly disclosed insider transactions (Form 4) for portfolio tickers
from SEC EDGAR. EDGAR needs no key but requires a descriptive User-Agent with
contact info (configured via TRADEER_SEC_USER_AGENT).

Only public, already-disclosed data is used (spec §4). Phase 2 records the fact
and date of each Form 4; detailed XML parsing of insider name / share counts is
left for a later refinement.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import requests

from config import get_settings
from connectors.positions import get_tickers
from storage import InsiderFiling, session_scope

logger = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_TIMEOUT = 20


def _headers() -> dict[str, str]:
    return {"User-Agent": get_settings().sec_user_agent, "Accept-Encoding": "gzip"}


@dataclass
class ParsedFiling:
    ticker: str
    filed_at: datetime | None
    accession: str | None


@lru_cache(maxsize=1)
def _ticker_cik_map() -> dict[str, str]:
    """Map ticker -> zero-padded 10-digit CIK. Cached for the process."""
    try:
        resp = requests.get(_TICKERS_URL, headers=_headers(), timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Failed to load SEC ticker->CIK map: %s", exc)
        return {}
    mapping: dict[str, str] = {}
    for row in data.values():
        sym = str(row.get("ticker", "")).upper()
        cik = row.get("cik_str")
        if sym and cik is not None:
            mapping[sym] = str(cik).zfill(10)
    return mapping


def get_cik(ticker: str) -> str | None:
    return _ticker_cik_map().get(ticker.upper())


def normalize_filings(submissions: dict | None, ticker: str) -> list[ParsedFiling]:
    """Extract Form 4 filings from an EDGAR submissions payload. Pure function."""
    out: list[ParsedFiling] = []
    if not submissions:
        return out
    recent = (submissions.get("filings", {}) or {}).get("recent", {}) or {}
    forms = recent.get("form", []) or []
    dates = recent.get("filingDate", []) or []
    accns = recent.get("accessionNumber", []) or []
    for i, form in enumerate(forms):
        if form != "4":
            continue
        filed_at = None
        if i < len(dates) and dates[i]:
            try:
                filed_at = datetime.strptime(dates[i], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pass
        accession = accns[i] if i < len(accns) else None
        out.append(ParsedFiling(ticker=ticker, filed_at=filed_at, accession=accession))
    return out


def fetch_filings(ticker: str) -> list[ParsedFiling]:
    cik = get_cik(ticker)
    if cik is None:
        logger.info("No CIK for %s (non-US?); skipping Form 4", ticker)
        return []
    try:
        resp = requests.get(
            _SUBMISSIONS_URL.format(cik=cik), headers=_headers(), timeout=_TIMEOUT
        )
        resp.raise_for_status()
        return normalize_filings(resp.json(), ticker)
    except Exception as exc:
        logger.warning("EDGAR submissions failed for %s: %s", ticker, exc)
        return []


def _persist(items: list[ParsedFiling]) -> int:
    """Insert filings, deduping by (ticker, filed_at, accession)."""
    saved = 0
    with session_scope() as session:
        for f in items:
            # accession is stored as JSON in transaction_type-free way: we use a
            # lightweight existence check on ticker+filed_at+stored accession.
            q = session.query(InsiderFiling.id).filter(
                InsiderFiling.ticker == f.ticker,
                InsiderFiling.filed_at == f.filed_at,
                InsiderFiling.insider_name == _accession_tag(f.accession),
            )
            if q.first():
                continue
            session.add(
                InsiderFiling(
                    ticker=f.ticker,
                    insider_name=_accession_tag(f.accession),
                    transaction_type="Form 4",
                    filed_at=f.filed_at,
                )
            )
            saved += 1
    return saved


def _accession_tag(accession: str | None) -> str | None:
    """Store the accession number in insider_name as a stable dedup key until
    detailed Form 4 XML parsing is added (then this is replaced by the real
    insider name)."""
    return f"acc:{accession}" if accession else None


def ingest(tickers: list[str]) -> int:
    total = 0
    for t in tickers:
        total += _persist(fetch_filings(t))
    logger.info("Ingested %d Form 4 filings", total)
    return total


def ingest_portfolio() -> int:
    return ingest(get_tickers())
