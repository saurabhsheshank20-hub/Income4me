"""
app.py
------
Nifty Overnight Screener & Intraday Tracker -- main Streamlit entry point.

Run with:
    streamlit run app.py

Wires together:
    config.py             constants & universes
    data_fetcher.py        Module 1: index & OHLCV ingestion
    screener.py             Module 2: overnight screener engine
    intraday_tracker.py     Module 3: 5-min signal tracker
    risk_calculator.py      Module 4: position size calculator
    charts.py                Module 5.2: Plotly figure builders
"""

from __future__ import annotations

import io
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import charts
import config
import indicators as ind
import intraday_tracker as it
import risk_calculator as rc
import screener as scr
from data_fetcher import fetch_daily_history, get_index_constituents, to_yf_ticker

try:
    from streamlit_autorefresh import st_autorefresh

    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False


# ==========================================================================
# Page config & session state
# ==========================================================================
st.set_page_config(page_title="Nifty Overnight Screener", page_icon="📈", layout="wide")

_DEFAULTS = {
    "screen_results": None,
    "screen_universe": None,
    "screen_time": None,
    "rc_entry": None,
    "rc_stop": None,
    "rc_symbol": None,
}
for key, val in _DEFAULTS.items():
    st.session_state.setdefault(key, val)


def market_status() -> tuple[bool, datetime]:
    """Informational only -- does not gate any button. Doesn't know NSE holidays."""
    now_ist = datetime.now(ZoneInfo(config.MARKET_TZ))
    is_weekday = now_ist.weekday() < 5
    open_t = dtime(config.MARKET_OPEN_HOUR, config.MARKET_OPEN_MINUTE)
    close_t = dtime(config.MARKET_CLOSE_HOUR, config.MARKET_CLOSE_MINUTE)
    is_open = is_weekday and (open_t <= now_ist.time() <= close_t)
    return is_open, now_ist


@st.cache_data(ttl=config.TTL_DAILY, show_spinner=False)
def get_daily_with_indicators(symbol: str) -> pd.DataFrame | None:
    """Daily OHLCV + SMA44/SMA200/EMA20/ATR/RVOL for one symbol, for the charting tab."""
    data = fetch_daily_history([symbol])
    df = data.get(symbol)
    if df is None or len(df) < config.MIN_BARS_REQUIRED:
        return None
    return scr.attach_daily_indicators(df)


# ==========================================================================
# Sidebar
# ==========================================================================
with st.sidebar:
    st.title("📈 Nifty Screener")
    st.caption("Overnight Technical Research & Intraday Signal Tracking")

    is_open, now_ist = market_status()
    status_label = "🟢 Market Open" if is_open else "🔴 Market Closed"
    st.markdown(f"**{status_label}**  \n{now_ist:%a, %d %b %Y · %H:%M} IST")
    st.caption("Doesn't account for NSE trading holidays.")

    st.markdown("---")
    universe = st.selectbox("Universe", config.UNIVERSE_CHOICES,
                             index=config.UNIVERSE_CHOICES.index(config.DEFAULT_UNIVERSE))

    symbols, source_note = get_index_constituents(universe)
    if source_note.startswith("⚠️"):
        st.warning(source_note)
    else:
        st.caption(f"Source: {source_note}")

    with st.expander("⚙️ Screening Criteria", expanded=False):
        pullback_pct = st.slider("Daily pullback band (± % of 44 SMA)", 0.5, 5.0,
                                  config.DEFAULT_PULLBACK_BAND_PCT, 0.1)
        require_rvol = st.checkbox("Require RVOL(10) > threshold", value=True)
        rvol_threshold = st.slider("RVOL threshold", 0.5, 3.0, config.DEFAULT_RVOL_THRESHOLD, 0.1,
                                    disabled=not require_rvol)
        fetch_sectors = st.checkbox("Fetch sector labels (slower)", value=True,
                                     help="Only called for stocks that already pass every other "
                                          "filter, but still adds a network round-trip each.")
        st.markdown("---")
        intraday_proximity_pct = st.slider("Intraday 'near support' band (± % of 44 SMA)", 0.1, 2.0,
                                            config.DEFAULT_INTRADAY_PROXIMITY_PCT, 0.05,
                                            help="Not specified numerically in the original brief -- "
                                                 "this is a configurable assumption for Module 3's "
                                                 "'touches or dips near' condition.")

    screen_params = scr.ScreenParams(
        pullback_pct=pullback_pct,
        rvol_threshold=rvol_threshold,
        require_rvol=require_rvol,
        fetch_sectors=fetch_sectors,
    )
    intraday_params = it.IntradayParams(proximity_pct=intraday_proximity_pct)

    st.markdown("---")
    if st.button("🔄 Force refresh data (clear cache)", use_container_width=True):
        st.cache_data.clear()
        st.session_state.screen_results = None
        st.rerun()

    st.markdown("---")
    st.caption(
        "⚠️ For research & education only. Not investment advice. Rule-based signals are "
        "unvalidated -- backtest and paper-trade before risking capital. Market data via "
        "Yahoo Finance (`yfinance`) is unofficial and may be delayed or occasionally "
        "unavailable."
    )

# ==========================================================================
# Tabs
# ==========================================================================
tab_overnight, tab_chart, tab_scanner, tab_risk = st.tabs(
    ["📋 Overnight Research", "📈 Interactive Charting", "⚡ Intraday Scanner", "🧮 Risk Calculator"]
)

# --------------------------------------------------------------------------
# TAB 1 -- Overnight Research (Module 2 + 5.1)
# --------------------------------------------------------------------------
with tab_overnight:
    st.subheader("Overnight Technical Research")
    st.caption(
        f"44 SMA > 200 SMA, both rising · Close within ±{pullback_pct:g}% of 44 SMA"
        + (f" · RVOL(10) > {rvol_threshold:g}" if require_rvol else "")
    )

    col_run, col_info = st.columns([1, 3])
    with col_run:
        run_clicked = st.button("▶ Run Overnight Screen", type="primary", use_container_width=True)
    with col_info:
        if st.session_state.screen_universe and st.session_state.screen_universe != universe:
            st.info(f"Universe changed to **{universe}** -- click **Run Overnight Screen** to update "
                    f"(showing results for **{st.session_state.screen_universe}** below).")

    if run_clicked:
        progress_bar = st.progress(0.0, text=f"Screening {universe} ({len(symbols)} stocks)...")
        try:
            results = scr.run_overnight_screener(
                symbols, screen_params,
                progress_callback=lambda frac: progress_bar.progress(frac, text=f"Screening... {frac*100:.0f}%"),
            )
            st.session_state.screen_results = results
            st.session_state.screen_universe = universe
            st.session_state.screen_time = now_ist
        finally:
            progress_bar.empty()

    results = st.session_state.screen_results
    if results is not None and not results.empty:
        st.caption(
            f"Last run: {st.session_state.screen_time:%d %b %Y, %H:%M IST} · "
            f"Universe: {st.session_state.screen_universe} · **{len(results)} matches**"
        )

        fcol1, fcol2 = st.columns([2, 2])
        with fcol1:
            sector_options = sorted(results["Sector"].dropna().unique().tolist())
            selected_sectors = st.multiselect("Filter by sector", sector_options)
        with fcol2:
            max_dist = float(results["Dist_to_SMA44_%"].abs().max()) if len(results) else 1.5
            dist_cap = st.slider("Max |distance to 44 SMA| %", 0.0, max(max_dist, 0.1),
                                  max(max_dist, 0.1), 0.05)

        filtered = results.copy()
        if selected_sectors:
            filtered = filtered[filtered["Sector"].isin(selected_sectors)]
        filtered = filtered[filtered["Dist_to_SMA44_%"].abs() <= dist_cap]

        st.dataframe(filtered, use_container_width=True, hide_index=True)

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            csv_bytes = filtered.to_csv(index=False).encode("utf-8")
            st.download_button("⬇ Export CSV", csv_bytes, file_name=f"overnight_screen_{universe.replace(' ', '')}.csv",
                                mime="text/csv", use_container_width=True)
        with dl_col2:
            xlsx_buf = io.BytesIO()
            with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
                filtered.to_excel(writer, index=False, sheet_name="Overnight Screen")
            st.download_button("⬇ Export Excel", xlsx_buf.getvalue(),
                                file_name=f"overnight_screen_{universe.replace(' ', '')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True)
    elif results is not None and results.empty:
        st.info("No stocks matched the current criteria. Try relaxing the filters in the sidebar, "
                "or switch to a larger universe.")
    else:
        st.info("Click **▶ Run Overnight Screen** to scan the selected universe. "
                "Scanning up to 500 stocks can take a minute or two.")

# --------------------------------------------------------------------------
# TAB 2 -- Interactive Charting (Module 5.2)
# --------------------------------------------------------------------------
with tab_chart:
    st.subheader("Interactive Charting")

    screened_symbols = (
        list(st.session_state.screen_results["Ticker"])
        if st.session_state.screen_results is not None and not st.session_state.screen_results.empty
        else []
    )
    chart_source = st.radio("Chart from", ["Screened stocks", "Full universe"],
                             index=0 if screened_symbols else 1, horizontal=True)
    chart_universe = screened_symbols if chart_source == "Screened stocks" else symbols

    if not chart_universe:
        st.info("No screened stocks yet -- run the Overnight Screen, or switch to 'Full universe'.")
    else:
        chart_symbol = st.selectbox("Stock", chart_universe)
        view = st.radio("View", ["View A -- Daily (44/200 SMA, 20 EMA)", "View B -- 5-Minute (VWAP, 20 EMA, 44 SMA line)"],
                         horizontal=True)

        with st.spinner(f"Loading {chart_symbol}..."):
            daily_df = get_daily_with_indicators(chart_symbol)

        if daily_df is None:
            st.error(f"Couldn't load enough daily history for {chart_symbol} (needs "
                      f"{config.MIN_BARS_REQUIRED}+ trading days). It may be too newly listed, "
                      f"or the data fetch failed -- try 'Force refresh data' in the sidebar.")
        else:
            latest = daily_df.iloc[-1]
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Close", f"₹{latest['Close']:.2f}")
            m2.metric("44 SMA", f"₹{latest['SMA_FAST']:.2f}")
            m3.metric("200 SMA", f"₹{latest['SMA_SLOW']:.2f}")
            m4.metric("20 EMA", f"₹{latest['EMA_FAST']:.2f}")
            m5.metric("ATR(14)", f"₹{latest['ATR']:.2f}")

            if view.startswith("View A"):
                st.plotly_chart(charts.plot_daily_chart(daily_df.tail(180), chart_symbol),
                                 use_container_width=True)
            else:
                sma44_value = float(latest["SMA_FAST"])
                with st.spinner("Loading 5-minute data..."):
                    signal = it.get_signal_for_stock(chart_symbol, sma44_value, intraday_params)
                if signal.status == it.SignalStatus.NO_DATA or signal.df is None:
                    st.warning("No usable 5-minute data right now -- this is normal outside NSE "
                               "market hours (09:15-15:30 IST) or if Yahoo Finance is rate-limiting.")
                else:
                    badge, label = it.STATUS_BADGE[signal.status]
                    st.markdown(f"### {badge} {label}")
                    s1, s2, s3, s4 = st.columns(4)
                    s1.metric("Close", f"₹{signal.close:.2f}")
                    s2.metric("VWAP", f"₹{signal.vwap:.2f}")
                    s3.metric("20 EMA (5m)", f"₹{signal.ema20:.2f}")
                    s4.metric("Dist. to 44 SMA", f"{signal.dist_to_sma44_pct:+.2f}%")
                    st.plotly_chart(charts.plot_intraday_chart(signal.df, chart_symbol, sma44_value),
                                     use_container_width=True)
                    st.caption(f"Last bar: {signal.last_bar_time} IST")

                    if signal.status == it.SignalStatus.BUY_CONFIRMED:
                        if st.button("🧮 Use this signal in Risk Calculator"):
                            st.session_state.rc_symbol = chart_symbol
                            st.session_state.rc_entry = signal.close
                            st.session_state.rc_stop = sma44_value
                            st.success("Loaded into the Risk Calculator tab -- switch tabs to see it.")

# --------------------------------------------------------------------------
# TAB 3 -- Intraday Scanner (Module 3 + 5.3)
# --------------------------------------------------------------------------
with tab_scanner:
    st.subheader("Intraday Scanner")
    st.caption("Tracks only the stocks that passed the Overnight Screen. 🟢 Buy Trigger Confirmed · "
               "🟡 Watching near 44 MA · 🔴 Invalidated · ⚪ Not near the level yet.")

    if st.session_state.screen_results is None or st.session_state.screen_results.empty:
        st.info("Run the **Overnight Screen** (first tab) to build a watchlist for the intraday scanner.")
    else:
        rcol1, rcol2, rcol3 = st.columns([1, 1, 2])
        with rcol1:
            manual_refresh = st.button("🔄 Refresh Now", use_container_width=True)
        with rcol2:
            auto_on = st.checkbox("Auto-refresh", value=False, disabled=not HAS_AUTOREFRESH)
        with rcol3:
            refresh_every = st.selectbox("Every", [1, 5], index=1, format_func=lambda m: f"{m} min",
                                          disabled=not (HAS_AUTOREFRESH and auto_on), label_visibility="collapsed")
        if not HAS_AUTOREFRESH:
            st.caption("💡 `pip install streamlit-autorefresh` to enable automatic refreshing -- "
                       "using the manual button for now.")
        elif auto_on:
            st_autorefresh(interval=refresh_every * 60 * 1000, key="intraday_autorefresh_tick")

        if not is_open:
            st.warning("Market looks closed right now (outside 09:15-15:30 IST, Mon-Fri) -- "
                       "5-minute data will likely be stale or unavailable.")

        watchlist = dict(zip(st.session_state.screen_results["Ticker"], st.session_state.screen_results["SMA_44"]))
        with st.spinner(f"Scanning {len(watchlist)} stocks..."):
            signals = it.scan_watchlist(watchlist, intraday_params)

        rows = []
        for s in signals:
            badge, label = it.STATUS_BADGE[s.status]
            rows.append({
                "Signal": f"{badge} {label}",
                "Ticker": s.symbol,
                "Close": s.close,
                "VWAP": s.vwap,
                "20 EMA (5m)": s.ema20,
                "44 SMA (daily)": s.sma44_daily,
                "Dist. to 44 SMA %": s.dist_to_sma44_pct,
                "Last Bar (IST)": s.last_bar_time,
            })
        scan_df = pd.DataFrame(rows)
        st.dataframe(scan_df, use_container_width=True, hide_index=True)

        n_buy = sum(1 for s in signals if s.status == it.SignalStatus.BUY_CONFIRMED)
        if n_buy:
            st.success(f"{n_buy} stock(s) showing a confirmed buy trigger right now.")

# --------------------------------------------------------------------------
# TAB 4 -- Risk Calculator (Module 4)
# --------------------------------------------------------------------------
with tab_risk:
    st.subheader("Risk Management & Position Size Calculator")
    if st.session_state.rc_symbol:
        st.caption(f"Prefilled from {st.session_state.rc_symbol}'s intraday buy signal -- adjust as needed.")

    c1, c2 = st.columns(2)
    with c1:
        capital = st.number_input("Capital (₹)", min_value=0.0, value=config.DEFAULT_CAPITAL, step=1000.0)
        risk_pct = st.number_input("Max Risk % per trade", min_value=0.01, max_value=100.0,
                                    value=config.DEFAULT_RISK_PCT, step=0.25)
        leverage = st.number_input("Brokerage Margin Leverage (MIS, x)", min_value=1.0, max_value=40.0,
                                    value=float(config.DEFAULT_LEVERAGE), step=1.0)
    with c2:
        entry_price = st.number_input("Entry Price (₹)", min_value=0.0,
                                       value=float(st.session_state.rc_entry or 0.0), step=0.05)
        stop_loss_price = st.number_input(
            "Stop-Loss Price (₹)", min_value=0.0, value=float(st.session_state.rc_stop or 0.0), step=0.05,
            help="Low of the 5-min signal candle, or the Daily 44 SMA line.",
        )

    result = rc.calculate_position(capital, risk_pct, entry_price, stop_loss_price, leverage,
                                    rr_targets=config.DEFAULT_RR_TARGETS)

    if not result.valid:
        if entry_price == 0 or stop_loss_price == 0:
            st.info("Enter an entry price and stop-loss to calculate position size.")
        else:
            st.error(result.error)
    else:
        for w in result.warnings:
            st.warning(w)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Max ₹ at Risk", f"₹{result.max_risk_amount:,.2f}")
        m2.metric("Position Size", f"{result.shares:,} shares")
        m3.metric("Trade Value", f"₹{result.trade_value:,.2f}")
        m4.metric("Required Margin", f"₹{result.required_margin:,.2f}")

        t1, t2 = st.columns(2)
        t1.metric("Target 1:1.5", f"₹{result.targets['1:1.5']:.2f}")
        t2.metric("Target 1:2", f"₹{result.targets['1:2']:.2f}")

        st.caption(f"Risk per share: ₹{result.risk_per_share:.2f} · "
                   f"Leverage: {leverage:g}x MIS · Capital: ₹{capital:,.0f}")
