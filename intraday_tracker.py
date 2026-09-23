"""
intraday_tracker.py
--------------------
Module 3: Morning Intraday Tracker (5-minute timeframe).

For a stock that already passed the overnight screen, pulls the latest 5-min
bar and classifies it into one of four states:

  BUY_CONFIRMED  (green badge)  -- ALL of:
      a) price is near the daily 44 SMA support band, AND
      b) the latest 5-min candle closed green (Close > Open), AND
      c) Close is above both the 5-min VWAP and the 5-min 20 EMA
  WATCHING       (yellow badge) -- near the support band, but (b) or (c) not yet met
  INVALIDATED    (red badge)    -- price has broken decisively below the band
  NOT_NEAR       (grey badge)   -- not currently near the level at all

Two assumptions fill gaps the brief leaves open (documented here, both
configurable from the sidebar rather than hardcoded):
  * "touches or dips near" the 44 SMA has no stated tolerance -- unlike
    Module 2's daily 1.5% pullback band -- so a separate, smaller intraday
    proximity band is used (default 0.3%).
  * A 4th neutral "NOT_NEAR" state is added beyond the brief's 3 colors, for
    stocks that are simply nowhere near their support level yet; without it,
    every stock would be forced into "watching" or "invalidated".
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import config
import indicators as ind
from data_fetcher import fetch_intraday_history


class SignalStatus:
    BUY_CONFIRMED = "BUY_CONFIRMED"
    WATCHING = "WATCHING"
    INVALIDATED = "INVALIDATED"
    NOT_NEAR = "NOT_NEAR"
    NO_DATA = "NO_DATA"


STATUS_BADGE = {
    SignalStatus.BUY_CONFIRMED: ("🟢", "Buy Trigger Confirmed"),
    SignalStatus.WATCHING: ("🟡", "Watching near 44 MA"),
    SignalStatus.INVALIDATED: ("🔴", "Invalidated"),
    SignalStatus.NOT_NEAR: ("⚪", "Not Near Level"),
    SignalStatus.NO_DATA: ("⚫", "No Data"),
}


@dataclass
class IntradayParams:
    proximity_pct: float = config.DEFAULT_INTRADAY_PROXIMITY_PCT
    invalidation_multiplier: float = config.INVALIDATION_MULTIPLIER


@dataclass
class SignalResult:
    symbol: str
    status: str
    close: float | None = None
    open_: float | None = None
    vwap: float | None = None
    ema20: float | None = None
    sma44_daily: float | None = None
    dist_to_sma44_pct: float | None = None
    last_bar_time: str | None = None
    df: pd.DataFrame | None = None  # full intraday frame, for charting


def get_signal_for_stock(
    symbol: str,
    sma44_daily_value: float,
    params: IntradayParams | None = None,
) -> SignalResult:
    params = params or IntradayParams()

    intraday_df = fetch_intraday_history(symbol)
    if intraday_df is None or intraday_df.empty or len(intraday_df) < config.EMA_FAST:
        return SignalResult(symbol=symbol, status=SignalStatus.NO_DATA, sma44_daily=sma44_daily_value)

    df = intraday_df.copy()
    df["VWAP"] = ind.vwap_session(df)
    df["EMA20"] = ind.ema(df["Close"], config.EMA_FAST)
    latest = df.iloc[-1]

    if pd.isna(latest["VWAP"]) or pd.isna(latest["EMA20"]):
        return SignalResult(symbol=symbol, status=SignalStatus.NO_DATA, sma44_daily=sma44_daily_value)

    band = params.proximity_pct / 100.0
    lower_band = sma44_daily_value * (1 - band)
    upper_band = sma44_daily_value * (1 + band)
    near_support = bool(
        (lower_band <= latest["Low"] <= upper_band) or (lower_band <= latest["Close"] <= upper_band)
    )
    green_candle = bool(latest["Close"] > latest["Open"])
    above_vwap_and_ema = bool(latest["Close"] > latest["VWAP"] and latest["Close"] > latest["EMA20"])
    decisively_broken = bool(latest["Close"] < sma44_daily_value * (1 - band * params.invalidation_multiplier))

    if near_support and green_candle and above_vwap_and_ema:
        status = SignalStatus.BUY_CONFIRMED
    elif near_support:
        status = SignalStatus.WATCHING
    elif decisively_broken:
        status = SignalStatus.INVALIDATED
    else:
        status = SignalStatus.NOT_NEAR

    dist_pct = float(ind.pct_distance(latest["Close"], sma44_daily_value))

    return SignalResult(
        symbol=symbol,
        status=status,
        close=round(float(latest["Close"]), 2),
        open_=round(float(latest["Open"]), 2),
        vwap=round(float(latest["VWAP"]), 2),
        ema20=round(float(latest["EMA20"]), 2),
        sma44_daily=round(float(sma44_daily_value), 2),
        dist_to_sma44_pct=round(dist_pct, 2),
        last_bar_time=df.index[-1].strftime("%Y-%m-%d %H:%M"),
        df=df,
    )


def scan_watchlist(
    symbols_with_sma44: dict[str, float],
    params: IntradayParams | None = None,
) -> list[SignalResult]:
    """Run get_signal_for_stock for every (symbol -> daily 44 SMA) pair given."""
    results = []
    for symbol, sma44_value in symbols_with_sma44.items():
        try:
            results.append(get_signal_for_stock(symbol, sma44_value, params))
        except Exception:
            results.append(SignalResult(symbol=symbol, status=SignalStatus.NO_DATA))
    # Sort so the most actionable signals surface first: BUY > WATCHING > NOT_NEAR > INVALIDATED > NO_DATA
    priority = {
        SignalStatus.BUY_CONFIRMED: 0,
        SignalStatus.WATCHING: 1,
        SignalStatus.NOT_NEAR: 2,
        SignalStatus.INVALIDATED: 3,
        SignalStatus.NO_DATA: 4,
    }
    results.sort(key=lambda r: priority.get(r.status, 9))
    return results
