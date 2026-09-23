"""
screener.py
-----------
Module 2: Overnight Screener Engine (daily timeframe).

Applies, per symbol:
  1. MA alignment  : 44 SMA > 200 SMA
     Slope (44)     : 44 SMA today > 44 SMA `SMA_FAST_SLOPE_LOOKBACK` sessions ago
     Slope (200)    : 200 SMA today > 200 SMA `SMA_SLOW_SLOPE_LOOKBACK` sessions ago
  2. Pullback band : Close within +/- pullback_pct% of the 44 SMA
  3. RVOL filter   : RVOL(10) > rvol_threshold (toggleable -- the brief states
                     it as a ">" condition, so it's implemented as a hard
                     filter by default, but can be switched off from the
                     sidebar if it's screening out too much)

"20 EMA status relative to 44 SMA" (also listed under Module 2's trend filters)
doesn't come with a numeric condition in the brief, so it's surfaced as an
informational "Above"/"Below" column rather than a pass/fail gate.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import config
import indicators as ind
from data_fetcher import fetch_daily_history, fetch_sector


@dataclass
class ScreenParams:
    pullback_pct: float = config.DEFAULT_PULLBACK_BAND_PCT
    rvol_threshold: float = config.DEFAULT_RVOL_THRESHOLD
    require_rvol: bool = True
    fetch_sectors: bool = True


def attach_daily_indicators(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add SMA_FAST (44), SMA_SLOW (200), EMA_FAST (20), ATR and RVOL columns to
    a raw daily OHLCV frame. Shared by the screener and by the Interactive
    Charting tab (View A) so both use exactly the same indicator math.
    """
    df = daily_df.copy()
    df["SMA_FAST"] = ind.sma(df["Close"], config.SMA_FAST)
    df["SMA_SLOW"] = ind.sma(df["Close"], config.SMA_SLOW)
    df["EMA_FAST"] = ind.ema(df["Close"], config.EMA_FAST)
    df["ATR"] = ind.atr(df, config.ATR_PERIOD)
    df["RVOL"] = ind.rvol(df["Volume"], config.RVOL_LOOKBACK)
    return df


def _screen_one(symbol: str, daily_df: pd.DataFrame, params: ScreenParams) -> dict | None:
    if daily_df is None or len(daily_df) < config.MIN_BARS_REQUIRED:
        return None  # not enough history (e.g. a recent listing)

    df = attach_daily_indicators(daily_df)

    if df[["SMA_FAST", "SMA_SLOW", "EMA_FAST", "ATR"]].iloc[-1].isna().any():
        return None  # indicators didn't fully warm up (shouldn't happen given MIN_BARS_REQUIRED, but be safe)

    latest = df.iloc[-1]
    sma_fast_ago = df["SMA_FAST"].iloc[-1 - config.SMA_FAST_SLOPE_LOOKBACK]
    sma_slow_ago = df["SMA_SLOW"].iloc[-1 - config.SMA_SLOW_SLOPE_LOOKBACK]

    ma_alignment = bool(latest["SMA_FAST"] > latest["SMA_SLOW"])
    fast_rising = bool(latest["SMA_FAST"] > sma_fast_ago)
    slow_rising = bool(latest["SMA_SLOW"] > sma_slow_ago)

    band = params.pullback_pct / 100.0
    lower_band = latest["SMA_FAST"] * (1 - band)
    upper_band = latest["SMA_FAST"] * (1 + band)
    in_pullback_zone = bool(lower_band <= latest["Close"] <= upper_band)

    rvol_value = latest["RVOL"]
    rvol_ok = bool(pd.notna(rvol_value) and rvol_value > params.rvol_threshold) if params.require_rvol else True

    passed = ma_alignment and fast_rising and slow_rising and in_pullback_zone and rvol_ok
    if not passed:
        return None

    sector = fetch_sector(symbol) if params.fetch_sectors else "N/A"

    return {
        "Ticker": symbol,
        "Sector": sector,
        "Close": round(float(latest["Close"]), 2),
        "SMA_44": round(float(latest["SMA_FAST"]), 2),
        "Dist_to_SMA44_%": round(float(ind.pct_distance(latest["Close"], latest["SMA_FAST"])), 2),
        "SMA_200": round(float(latest["SMA_SLOW"]), 2),
        "EMA_20": round(float(latest["EMA_FAST"]), 2),
        "EMA20_vs_SMA44": "Above" if latest["EMA_FAST"] > latest["SMA_FAST"] else "Below",
        "ATR_14": round(float(latest["ATR"]), 2),
        "RVOL_10": round(float(rvol_value), 2) if pd.notna(rvol_value) else None,
        "Date": df.index[-1].strftime("%Y-%m-%d"),
    }


def run_overnight_screener(
    symbols: list[str],
    params: ScreenParams | None = None,
    progress_callback=None,
) -> pd.DataFrame:
    """
    Run the full overnight screen over `symbols` (bare NSE symbols, no .NS).
    Returns a DataFrame of passing stocks, one row each, sorted by how close
    price is sitting to the 44 SMA (tightest pullbacks first).
    """
    params = params or ScreenParams()
    daily_data = fetch_daily_history(symbols)

    rows = []
    total = max(len(symbols), 1)
    for idx, symbol in enumerate(symbols):
        try:
            row = _screen_one(symbol, daily_data.get(symbol), params)
            if row:
                rows.append(row)
        except Exception:
            pass  # one bad symbol should never abort the whole screen
        if progress_callback:
            progress_callback(min((idx + 1) / total, 1.0))

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.reindex(result["Dist_to_SMA44_%"].abs().sort_values().index).reset_index(drop=True)
    return result
