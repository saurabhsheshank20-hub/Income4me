"""
indicators.py
-------------
Technical indicator calculations used by the screener and intraday tracker.

These are implemented directly on top of pandas/numpy rather than via
`pandas_ta` or `ta`. That's a deliberate choice for this project, not an
oversight of the brief:
  * `pandas_ta` has had repeated breakage against modern numpy (it imports
    the long-removed `numpy.NaN`), which makes it a fragile dependency for
    something meant to run unattended before market open.
  * The formulas needed here (SMA, EMA, Wilder ATR, session VWAP, RVOL) are
    short and worth having transparent and testable in-house.
If you'd rather use `ta` or `pandas_ta`, these functions are drop-in
replaceable -- every function here takes/returns plain pandas Series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    """Exponential moving average (standard span-based EMA)."""
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    """True Range = max(H-L, |H-Cprev|, |L-Cprev|)."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range using Wilder-style smoothing.

    Implemented as an EWM with alpha = 1/period (adjust=False), which is the
    standard, numerically-stable approximation of Wilder's original
    "seed with an SMA, then recursively smooth" method used by most
    charting platforms. Differences versus a hand-rolled Wilder recursion
    are negligible once past the warm-up window.
    """
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rvol(volume: pd.Series, lookback: int = 10) -> pd.Series:
    """
    Relative Volume = today's volume / average volume of the prior
    `lookback` sessions (today is excluded from its own average via shift(1)).
    """
    avg_prior_volume = volume.shift(1).rolling(window=lookback, min_periods=lookback).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        result = volume / avg_prior_volume
    return result.replace([np.inf, -np.inf], np.nan)


def is_rising(series: pd.Series, lookback: int) -> pd.Series:
    """Boolean series: True where series[t] > series[t - lookback]."""
    return series > series.shift(lookback)


def pct_distance(price: pd.Series, level: pd.Series | float) -> pd.Series:
    """Signed % distance of `price` from `level`: (price - level) / level * 100."""
    return (price - level) / level * 100.0


def vwap_session(df: pd.DataFrame) -> pd.Series:
    """
    Intraday VWAP that resets every calendar session (day), computed from a
    DatetimeIndex. Uses the typical price (H+L+C)/3 as is standard.

    Expects `df.index` to be a tz-aware or tz-naive DatetimeIndex sorted
    ascending; if multiple sessions are present (e.g. a 5-day, 5-min pull),
    VWAP restarts at zero at the first bar of each session rather than
    accumulating across days.
    """
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3.0
    tp_vol = typical_price * df["Volume"]

    session_key = df.index.date  # groups bars by calendar date
    cum_tp_vol = tp_vol.groupby(session_key).cumsum()
    cum_vol = df["Volume"].groupby(session_key).cumsum()

    with np.errstate(divide="ignore", invalid="ignore"):
        result = cum_tp_vol / cum_vol
    return result.replace([np.inf, -np.inf], np.nan)
