from __future__ import annotations

from connectors import filings


def test_normalize_filings_filters_form4():
    submissions = {
        "filings": {
            "recent": {
                "form": ["4", "10-K", "4", "8-K"],
                "filingDate": ["2026-05-01", "2026-04-01", "2026-05-10", "x"],
                "accessionNumber": ["acc-1", "acc-2", "acc-3", "acc-4"],
            }
        }
    }
    out = filings.normalize_filings(submissions, "ACME")
    assert len(out) == 2
    assert {f.accession for f in out} == {"acc-1", "acc-3"}
    assert out[0].ticker == "ACME"
    assert out[0].filed_at is not None and out[0].filed_at.year == 2026


def test_normalize_filings_empty():
    assert filings.normalize_filings(None, "X") == []
    assert filings.normalize_filings({}, "X") == []


def test_persist_filings_dedup(db):
    items = filings.normalize_filings(
        {
            "filings": {
                "recent": {
                    "form": ["4"],
                    "filingDate": ["2026-05-01"],
                    "accessionNumber": ["acc-1"],
                }
            }
        },
        "ACME",
    )
    assert filings._persist(items) == 1
    assert filings._persist(items) == 0  # duplicate skipped
