"""
data_fetcher.py
----------------
Module 1: Index & Data Ingestion.

Everything that talks to the outside world (NSE Indices for constituent
lists, Yahoo Finance via yfinance for OHLCV) lives here, wrapped in
try/except so a single bad ticker, a timeout, or a blocked endpoint degrades
gracefully instead of crashing the whole app.

Caching: functions are decorated with @st.cache_data so repeated tab
switches don't re-trigger full re-downloads. Use the "Force refresh" button
in the sidebar (calls st.cache_data.clear()) to bust the cache manually.
"""

from __future__ import annotations

import io
import json
import time

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

import config


# --------------------------------------------------------------------------
# Symbols
# --------------------------------------------------------------------------
def to_yf_ticker(symbol: str) -> str:
    """Append the NSE suffix, e.g. 'RELIANCE' -> 'RELIANCE.NS'."""
    return f"{symbol}{config.NSE_SUFFIX}"


def _load_json_override(universe: str) -> list[str] | None:
    if not config.UNIVERSE_JSON_OVERRIDE.exists():
        return None
    try:
        data = json.loads(config.UNIVERSE_JSON_OVERRIDE.read_text())
        symbols = data.get(universe)
        if symbols:
            return [str(s).strip().upper() for s in symbols if str(s).strip()]
    except (json.JSONDecodeError, OSError):
        return None
    return None


def _fetch_nse_index_csv(url: str) -> list[str]:
    """Download an NSE Indices constituent CSV and extract the Symbol column."""
    resp = requests.get(url, headers=config.HTTP_HEADERS, timeout=10)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    symbol_col = next((c for c in df.columns if "symbol" in c.lower()), None)
    if symbol_col is None:
        raise ValueError(f"No 'Symbol' column found in CSV from {url}")
    symbols = df[symbol_col].dropna().astype(str).str.strip().str.upper().tolist()
    symbols = [s for s in symbols if s]
    if not symbols:
        raise ValueError(f"CSV from {url} parsed but yielded no symbols")
    return symbols


@st.cache_data(ttl=config.TTL_UNIVERSE, show_spinner=False)
def get_index_constituents(universe: str) -> tuple[list[str], str]:
    """
    Resolve a universe name (e.g. "Nifty 200") to a list of bare NSE symbols
    (no .NS suffix). Returns (symbols, source_note) where source_note
    explains where the list came from, for display in the UI.

    Resolution order: local JSON override -> live NSE Indices CSV -> hardcoded
    Nifty 50 fallback (only ever substituted with a clear note, never silently).
    """
    override = _load_json_override(universe)
    if override:
        return override, f"local override (universes.json, {len(override)} symbols)"

    if universe == "Nifty 50":
        symbols = [sym for sym, _ in config.NIFTY_50]
        return symbols, f"built-in list ({len(symbols)} symbols)"

    url = config.INDEX_CSV_URLS.get(universe)
    if url:
        try:
            symbols = _fetch_nse_index_csv(url)
            return symbols, f"live NSE Indices fetch ({len(symbols)} symbols)"
        except Exception as exc:  # network error, HTML instead of CSV, bad format, etc.
            fallback = [sym for sym, _ in config.NIFTY_50]
            return (
                fallback,
                f"⚠️ could not fetch {universe} from NSE ({exc.__class__.__name__}); "
                f"showing Nifty 50 instead -- add a universes.json override to fix this",
            )

    fallback = [sym for sym, _ in config.NIFTY_50]
    return fallback, "⚠️ unknown universe; showing Nifty 50"


# --------------------------------------------------------------------------
# OHLCV cleaning helpers
# --------------------------------------------------------------------------
_REQUIRED_COLS = {"Open", "High", "Low", "Close", "Volume"}


def _clean_ohlcv(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        # yfinance orders MultiIndex levels differently depending on the call
        # (group_by='ticker' -> (ticker, field); default -> (field, ticker)).
        # Rather than assume which level is which, flatten to whichever level
        # actually contains the OHLCV field names.
        flattened = None
        for level in range(df.columns.nlevels):
            if _REQUIRED_COLS.issubset(set(df.columns.get_level_values(level))):
                flattened = df.columns.get_level_values(level)
                break
        if flattened is None:
            return None
        df.columns = flattened
    if not _REQUIRED_COLS.issubset(set(df.columns)):
        return None
    df = df.dropna(subset=["Close"], how="any")
    df = df.dropna(how="all")
    return df if not df.empty else None


def _ensure_ist(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None:
        return None
    try:
        if df.index.tz is None:
            df.index = df.index.tz_localize(config.MARKET_TZ)
        else:
            df.index = df.index.tz_convert(config.MARKET_TZ)
    except Exception:
        pass  # leave index as-is if tz handling fails; downstream code tolerates this
    return df


# --------------------------------------------------------------------------
# Daily OHLCV (Module 2: Overnight Screener)
# --------------------------------------------------------------------------
@st.cache_data(ttl=config.TTL_DAILY, show_spinner=False)
def fetch_daily_history(
    symbols: list[str],
    period: str = config.DAILY_HISTORY_PERIOD,
    interval: str = "1d",
    batch_size: int = 50,
) -> dict[str, pd.DataFrame]:
    """
    Batch-download daily OHLCV for a list of bare symbols (no .NS) via
    yfinance, chunked to keep individual requests small and reduce
    rate-limiting risk. Returns {symbol: DataFrame | None}; a None value
    means that symbol failed or had no usable data (caller should skip it).
    """
    results: dict[str, pd.DataFrame | None] = {}
    yf_tickers = [to_yf_ticker(s) for s in symbols]
    ticker_to_symbol = dict(zip(yf_tickers, symbols))

    for i in range(0, len(yf_tickers), batch_size):
        batch = yf_tickers[i : i + batch_size]
        try:
            raw = yf.download(
                tickers=batch,
                period=period,
                interval=interval,
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=True,
            )
        except Exception:
            for t in batch:
                results[ticker_to_symbol[t]] = None
            continue

        if raw is None or raw.empty:
            for t in batch:
                results[ticker_to_symbol[t]] = None
        elif len(batch) == 1:
            # yfinance can return a flat (non-MultiIndex) frame for a single ticker
            sym = ticker_to_symbol[batch[0]]
            df = raw if not isinstance(raw.columns, pd.MultiIndex) else raw.get(batch[0])
            results[sym] = _clean_ohlcv(df)
        else:
            for t in batch:
                sym = ticker_to_symbol[t]
                try:
                    df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else None
                    results[sym] = _clean_ohlcv(df)
                except Exception:
                    results[sym] = None

        time.sleep(0.3)  # small pause between batches to ease rate limiting

    return results


# --------------------------------------------------------------------------
# Intraday OHLCV (Module 3: Intraday Tracker) -- single ticker at a time,
# called only for the (small) set of stocks that already passed the
# overnight screen, so batching isn't needed here.
# --------------------------------------------------------------------------
@st.cache_data(ttl=config.TTL_INTRADAY, show_spinner=False)
def fetch_intraday_history(
    symbol: str,
    period: str = config.INTRADAY_PERIOD,
    interval: str = config.INTRADAY_INTERVAL,
) -> pd.DataFrame | None:
    """Download 5-min OHLCV for one symbol. Returns None on any failure."""
    yf_ticker = to_yf_ticker(symbol)
    try:
        raw = yf.download(
            tickers=yf_ticker,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
            threads=False,
        )
    except Exception:
        return None

    df = _clean_ohlcv(raw)
    df = _ensure_ist(df)
    return df


@st.cache_data(ttl=config.TTL_DAILY, show_spinner=False)
def fetch_sector(symbol: str) -> str:
    """
    Best-effort sector lookup via yfinance's slow `.info` call. Only ever
    call this for a *small* set of already-screened tickers -- calling it
    for a full 500-stock universe would make the screener unusably slow and
    is a common way people accidentally get rate-limited.
    """
    if symbol in config.NIFTY_50_SECTORS:
        return config.NIFTY_50_SECTORS[symbol]
    try:
        info = yf.Ticker(to_yf_ticker(symbol)).info
        return info.get("sector") or info.get("industry") or "N/A"
    except Exception:
        return "N/A"
