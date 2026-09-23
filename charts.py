"""
charts.py
---------
Module 5.2: Interactive Charting Tab -- Plotly figure builders.

View A (daily):    candlesticks + 44 SMA (blue) + 200 SMA (red) + 20 EMA (green)
View B (intraday):  candlesticks + VWAP + 20 EMA(5m) + a static horizontal
                     line at the daily 44 SMA value (the "support" level the
                     whole strategy pivots around)
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

CANDLE_INCREASING = "#26a69a"
CANDLE_DECREASING = "#ef5350"


def _base_layout(fig: go.Figure, title: str, height: int = 560) -> go.Figure:
    fig.update_layout(
        title=title,
        height=height,
        template="plotly_white",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=60, b=30),
        hovermode="x unified",
    )
    return fig


def plot_daily_chart(df: pd.DataFrame, symbol: str) -> go.Figure:
    """
    View A: 1-Day chart. Expects df to already contain SMA_FAST (44), SMA_SLOW
    (200) and EMA_FAST (20) columns, as produced by screener._screen_one /
    indicators.py.
    """
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name=symbol,
            increasing_line_color=CANDLE_INCREASING,
            decreasing_line_color=CANDLE_DECREASING,
        )
    )
    if "SMA_FAST" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["SMA_FAST"], name="44 SMA",
                                  line=dict(color="blue", width=1.5)))
    if "SMA_SLOW" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["SMA_SLOW"], name="200 SMA",
                                  line=dict(color="red", width=1.5)))
    if "EMA_FAST" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["EMA_FAST"], name="20 EMA",
                                  line=dict(color="green", width=1.5)))
    return _base_layout(fig, f"{symbol} -- Daily (44/200 SMA, 20 EMA)")


def plot_intraday_chart(df: pd.DataFrame, symbol: str, daily_sma44_value: float) -> go.Figure:
    """
    View B: 5-minute chart. Expects df to already contain VWAP and EMA20
    columns, as produced by intraday_tracker.get_signal_for_stock.
    """
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name=symbol,
            increasing_line_color=CANDLE_INCREASING,
            decreasing_line_color=CANDLE_DECREASING,
        )
    )
    if "VWAP" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["VWAP"], name="VWAP",
                                  line=dict(color="orange", width=1.5)))
    if "EMA20" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["EMA20"], name="20 EMA (5m)",
                                  line=dict(color="green", width=1.5)))
    fig.add_hline(
        y=daily_sma44_value,
        line_dash="dash",
        line_color="blue",
        annotation_text=f"Daily 44 SMA ({daily_sma44_value:.2f})",
        annotation_position="top left",
    )
    return _base_layout(fig, f"{symbol} -- 5-Minute (VWAP, 20 EMA, Daily 44 SMA)")
