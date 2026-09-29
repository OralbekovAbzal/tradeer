from __future__ import annotations

from connectors import positions


def test_parse_csv_plain(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("ticker,qty,avg_price,sector\naapl,20,165.5,Technology\n", encoding="utf-8")
    rows = positions.parse_csv(f)
    assert len(rows) == 1
    assert rows[0].ticker == "AAPL"
    assert rows[0].qty == 20
    assert rows[0].avg_price == 165.5
    assert rows[0].sector == "Technology"


def test_parse_csv_excel_bom(tmp_path):
    # Excel "CSV UTF-8" prepends a BOM and uses CRLF line endings.
    f = tmp_path / "p.csv"
    f.write_bytes(b"\xef\xbb\xbfticker,qty,avg_price\r\nMSFT,10,390\r\n")
    rows = positions.parse_csv(f)
    assert [r.ticker for r in rows] == ["MSFT"]
