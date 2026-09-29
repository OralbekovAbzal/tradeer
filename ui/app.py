"""Streamlit dashboard (spec M8, Phase 1).

Run with:  streamlit run ui/app.py

Shows: portfolio overview, P&L, allocation, risk flags, and the trading
journal with discipline stats. Read-only view over the local SQLite database.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `streamlit run ui/app.py` to import project packages.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from alerts import engine as alert_engine
from alerts import telegram_bot
from analysis import (
    correlations,
    history,
    journal,
    metrics,
    report as report_mod,
    research,
    risk,
    scenarios,
)
from connectors import filings, market, news
from connectors import positions as positions_io
from storage import (
    AlertLog,
    Event,
    InsiderFiling,
    JournalEntry,
    News,
    Position,
    init_db,
    session_scope,
)

st.set_page_config(page_title="Trading Co-Pilot", layout="wide")
init_db()


def _positions_df() -> pd.DataFrame:
    with session_scope() as session:
        rows = session.query(Position).all()
        data = [
            {
                "ticker": p.ticker,
                "qty": p.qty,
                "avg_price": p.avg_price,
                "current_price": p.current_price,
                "market_value": p.market_value
                or ((p.current_price or p.avg_price) * p.qty),
                "sector": p.sector or "Unknown",
                "unrealized_pnl": (
                    ((p.current_price or p.avg_price) - p.avg_price) * p.qty
                ),
            }
            for p in rows
        ]
    return pd.DataFrame(data)


st.title("Trading Co-Pilot")
st.caption(
    "Read-only assistant. Shows facts, risk and context — never buy/sell advice."
)

with st.sidebar:
    st.header("Data")
    if not market.is_available():
        st.warning("yfinance unavailable — prices will not refresh.")
    uploaded = st.file_uploader("Import positions CSV", type="csv")
    if uploaded is not None and st.button("Import"):
        tmp = Path("data") / "_upload.csv"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(uploaded.getvalue())
        try:
            n = positions_io.import_csv(tmp)
            st.success(f"Imported {n} positions.")
        except Exception as exc:
            st.error(f"Import failed: {exc}")
        finally:
            tmp.unlink(missing_ok=True)
    if st.button("Refresh prices (yfinance)"):
        with st.spinner("Fetching prices..."):
            n = positions_io.refresh_prices(lookup_sector=True)
        st.success(f"Updated {n} positions.")

    st.divider()
    st.subheader("Information layer")
    st.caption(
        f"Finnhub: {'on' if news.is_available() else 'off (no key)'} · "
        f"Telegram: {'on' if telegram_bot.is_configured() else 'off'}"
    )
    if st.button("Fetch news & earnings"):
        with st.spinner("Querying Finnhub..."):
            r = news.ingest_portfolio()
        st.success(f"News +{r['news']}, earnings +{r['earnings']}.")
    if st.button("Fetch Form 4 filings"):
        with st.spinner("Querying SEC EDGAR..."):
            n = filings.ingest_portfolio()
        st.success(f"Form 4 filings +{n}.")
    if st.button("Run alerts now"):
        n = alert_engine.run()
        st.success(f"Dispatched {n} new alerts.")

    st.divider()
    st.subheader("Analytics layer")
    st.caption(f"Claude: {'on' if research.is_available() else 'off (no key)'}")
    if st.button("Refresh price history"):
        with st.spinner("Caching daily closes..."):
            n = history.refresh_portfolio_history()
        st.success(f"Cached {n} price-history rows.")

df = _positions_df()

tab_overview, tab_risk, tab_journal, tab_info, tab_deep = st.tabs(
    ["Overview", "Risk", "Journal", "News & Events", "Deep Analysis"]
)

with tab_overview:
    if df.empty:
        st.info("No positions yet. Import a CSV from the sidebar to begin.")
    else:
        total = float(df["market_value"].sum())
        pnl = float(df["unrealized_pnl"].sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Portfolio value", f"${total:,.2f}")
        c2.metric("Unrealized P&L", f"${pnl:,.2f}")
        c3.metric("Positions", str(len(df)))
        st.subheader("Positions")
        st.dataframe(df, width="stretch")
        st.subheader("Allocation by position")
        alloc = df.set_index("ticker")["market_value"]
        st.bar_chart(alloc)

with tab_risk:
    report = risk.build_report()
    if report.total_value <= 0:
        st.info("No positions to analyze.")
    else:
        if report.flags:
            for f in report.flags:
                st.warning(f"[{f.code}] {f.message}")
        else:
            st.success("No risk thresholds breached.")
        st.subheader("Position concentration")
        st.dataframe(
            pd.DataFrame(
                [
                    {"ticker": c.ticker, "weight": c.weight, "value": c.market_value}
                    for c in report.positions
                ]
            ),
            width="stretch",
        )
        st.subheader("Sector concentration")
        st.dataframe(
            pd.DataFrame(
                [
                    {"sector": s.sector, "weight": s.weight, "value": s.market_value}
                    for s in report.sectors
                ]
            ),
            width="stretch",
        )

with tab_journal:
    st.subheader("New thesis (record before entering)")
    with st.form("new_entry", clear_on_submit=True):
        j_ticker = st.text_input("Ticker")
        j_thesis = st.text_area("Thesis — why are you entering?")
        j_entry = st.text_input("Entry condition")
        j_tp = st.text_input("Take-profit rule")
        j_stop = st.text_input("Stop / 'I was wrong' rule")
        if st.form_submit_button("Save thesis"):
            try:
                journal.open_entry(
                    j_ticker, j_thesis, j_entry or None, j_tp or None, j_stop or None
                )
                st.success("Thesis recorded.")
            except Exception as exc:
                st.error(str(exc))

    stats = journal.compute_stats()
    st.subheader("Discipline stats")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Closed trades", str(stats.closed))
    c2.metric("Win rate", f"{stats.win_rate:.0%}")
    c3.metric("Followed rules", f"{stats.rule_follow_rate:.0%}")
    c4.metric("Win% when followed", f"{stats.win_rate_when_followed:.0%}")

    st.subheader("Entries")
    with session_scope() as session:
        entries = session.query(JournalEntry).order_by(
            JournalEntry.opened_at.desc()
        ).all()
        edata = [
            {
                "id": e.id,
                "ticker": e.ticker,
                "thesis": e.thesis,
                "opened_at": e.opened_at,
                "closed_at": e.closed_at,
                "outcome": e.outcome,
                "followed_rules": e.followed_rules,
            }
            for e in entries
        ]
    st.dataframe(pd.DataFrame(edata), width="stretch")

    st.subheader("Close an entry")
    with st.form("close_entry", clear_on_submit=True):
        cid = st.number_input("Entry id", min_value=1, step=1)
        outcome = st.selectbox("Outcome", ["win", "loss", "flat"])
        followed = st.checkbox("Followed my own rules", value=True)
        cnotes = st.text_input("Notes")
        if st.form_submit_button("Close"):
            try:
                journal.close_entry(int(cid), outcome, followed, cnotes or None)
                st.success("Entry closed.")
            except Exception as exc:
                st.error(str(exc))

with tab_info:
    st.caption(
        "Information and context only — never a buy/sell recommendation."
    )
    with session_scope() as session:
        news_rows = [
            {
                "ticker": n.ticker,
                "published_at": n.published_at,
                "headline": n.headline,
                "source": n.source,
                "url": n.url,
            }
            for n in session.query(News)
            .order_by(News.published_at.desc())
            .limit(100)
            .all()
        ]
        event_rows = [
            {
                "ticker": e.ticker,
                "type": e.type,
                "event_date": e.event_date,
                "payload": e.payload,
            }
            for e in session.query(Event)
            .order_by(Event.event_date.asc())
            .limit(100)
            .all()
        ]
        filing_rows = [
            {
                "ticker": f.ticker,
                "filed_at": f.filed_at,
                "transaction_type": f.transaction_type,
            }
            for f in session.query(InsiderFiling)
            .order_by(InsiderFiling.filed_at.desc())
            .limit(100)
            .all()
        ]
        alert_rows = [
            {
                "sent_at": a.sent_at,
                "type": a.type,
                "ticker": a.ticker,
                "message": a.message,
                "channel": a.channel,
            }
            for a in session.query(AlertLog)
            .order_by(AlertLog.sent_at.desc())
            .limit(100)
            .all()
        ]

    st.subheader("News")
    st.dataframe(pd.DataFrame(news_rows), width="stretch")
    st.subheader("Upcoming earnings & events")
    st.dataframe(pd.DataFrame(event_rows), width="stretch")
    st.subheader("Insider filings (Form 4)")
    st.dataframe(pd.DataFrame(filing_rows), width="stretch")
    st.subheader("Alerts log")
    st.dataframe(pd.DataFrame(alert_rows), width="stretch")

with tab_deep:
    st.caption(
        "Advanced analytics: risk metrics, correlations, stress tests and an "
        "optional Claude report. Informational only — not buy/sell advice."
    )

    m = metrics.build_metrics()
    if m.note and not m.positions:
        st.info(m.note)
    else:
        st.subheader("Risk metrics")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Beta", f"{m.beta:.2f}")
        c2.metric("Annual vol", f"{m.annual_vol:.1%}")
        c3.metric("VaR 95% (hist)", f"{m.var_95_hist:.2%}")
        c4.metric("Max drawdown", f"{m.max_drawdown:.1%}")
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Annual return", f"{m.annual_return:.1%}")
        c6.metric("VaR 95% (param)", f"{m.var_95_param:.2%}")
        c7.metric("Sharpe", f"{m.sharpe:.2f}")
        c8.metric("Sortino", f"{m.sortino:.2f}")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "ticker": p.ticker,
                        "weight": p.weight,
                        "annual_vol": p.annual_vol,
                        "beta": p.beta,
                    }
                    for p in m.positions
                ]
            ),
            width="stretch",
        )

    st.subheader("Correlations & hidden clusters")
    corr = correlations.build_report()
    if corr.note:
        st.info(corr.note)
    else:
        if not corr.matrix.empty:
            st.dataframe(
                corr.matrix.style.background_gradient(
                    cmap="RdYlGn_r", vmin=-1, vmax=1
                ).format("{:.2f}"),
                width="stretch",
            )
        if corr.clusters:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "cluster": ", ".join(cl.tickers),
                            "combined_weight": cl.weight,
                            "avg_corr": cl.avg_corr,
                        }
                        for cl in corr.clusters
                    ]
                ),
                width="stretch",
            )
        else:
            st.caption("No correlation clusters above threshold.")

    st.subheader("Stress scenarios")
    scen = scenarios.build_report()
    if scen.note and not scen.results:
        st.info(scen.note)
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "scenario": r.name,
                        "pct_impact": r.pct_impact,
                        "value_impact": r.value_impact,
                    }
                    for r in scen.results
                ]
            ),
            width="stretch",
        )
        if scen.note:
            st.caption(scen.note)

    st.divider()
    st.subheader("Claude analytical report")
    if not research.is_available():
        st.info(research._unavailable_note())
    include_opinion = st.checkbox(
        "Include Claude's optional opinion (with disclaimer)", value=False
    )
    if st.button("Generate deep report"):
        with st.spinner("Assembling report..."):
            md, path = report_mod.generate(
                include_opinion=include_opinion, save=True
            )
        st.session_state["deep_report_md"] = md
        st.session_state["deep_report_path"] = str(path) if path else None

    if st.session_state.get("deep_report_md"):
        md = st.session_state["deep_report_md"]
        st.markdown(md)
        st.download_button(
            "Download report (.md)",
            data=md,
            file_name="tradeer_report.md",
            mime="text/markdown",
        )
        if st.session_state.get("deep_report_path"):
            st.caption(f"Saved to {st.session_state['deep_report_path']}")
