"""
config.py
---------
Central configuration for the Nifty Overnight Screener & Intraday Tracker.

Holds index universes, strategy parameters (MA periods, pullback bands, risk
defaults) and small constants, so the rest of the codebase has no magic
numbers scattered through it.

NOTE ON INDEX CONSTITUENTS
---------------------------
NSE Indices rebalances the Nifty 100 / 200 / 500 semi-annually (and Nifty 50
too, on the same cycle), so hardcoding ~500 tickers in this file would go
stale within months and could silently mislead the screener. Instead:

  * NIFTY_50 below is hardcoded from the official constituent list (accurate
    as of the Dec-2025 NSE Indices factsheet) and doubles as an offline
    fallback if the live fetch fails.
  * Nifty 100 / 200 / 500 constituents are fetched at runtime from the
    official NSE Indices CSV endpoints (see data_fetcher.get_index_constituents),
    cached for a day.
  * You can also drop a `universes.json` file next to app.py to pin your own
    lists -- handy if NSE's endpoints are unreachable from your network
    (common on cloud hosts) or you maintain a custom watchlist. Format:
        {"Nifty 200": ["RELIANCE", "TCS", ...]}
"""

from pathlib import Path

# --------------------------------------------------------------------------
# Index universes
# --------------------------------------------------------------------------

# Nifty 50 constituents: (NSE symbol without .NS suffix, sector).
# Source: official NSE Indices constituent list, accurate as of Dec 2025.
# Used both as a selectable universe and as the ultimate offline fallback
# for the larger universes if the live NSE fetch fails.
NIFTY_50 = [
    ("ADANIENT", "Metals & Mining"),
    ("ADANIPORTS", "Services"),
    ("APOLLOHOSP", "Healthcare"),
    ("ASIANPAINT", "Consumer Durables"),
    ("AXISBANK", "Financial Services"),
    ("BAJAJ-AUTO", "Automobile and Auto Components"),
    ("BAJFINANCE", "Financial Services"),
    ("BAJAJFINSV", "Financial Services"),
    ("BEL", "Capital Goods"),
    ("BHARTIARTL", "Telecommunication"),
    ("CIPLA", "Healthcare"),
    ("COALINDIA", "Oil, Gas & Consumable Fuels"),
    ("DRREDDY", "Healthcare"),
    ("EICHERMOT", "Automobile and Auto Components"),
    ("ETERNAL", "Consumer Services"),
    ("GRASIM", "Construction Materials"),
    ("HCLTECH", "Information Technology"),
    ("HDFCBANK", "Financial Services"),
    ("HDFCLIFE", "Financial Services"),
    ("HINDALCO", "Metals & Mining"),
    ("HINDUNILVR", "Fast Moving Consumer Goods"),
    ("ICICIBANK", "Financial Services"),
    ("INDIGO", "Services"),
    ("INFY", "Information Technology"),
    ("ITC", "Fast Moving Consumer Goods"),
    ("JIOFIN", "Financial Services"),
    ("JSWSTEEL", "Metals & Mining"),
    ("KOTAKBANK", "Financial Services"),
    ("LT", "Construction"),
    ("M&M", "Automobile and Auto Components"),
    ("MARUTI", "Automobile and Auto Components"),
    ("MAXHEALTH", "Healthcare"),
    ("NESTLEIND", "Fast Moving Consumer Goods"),
    ("NTPC", "Power"),
    ("ONGC", "Oil, Gas & Consumable Fuels"),
    ("POWERGRID", "Power"),
    ("RELIANCE", "Oil, Gas & Consumable Fuels"),
    ("SBILIFE", "Financial Services"),
    ("SHRIRAMFIN", "Financial Services"),
    ("SBIN", "Financial Services"),
    ("SUNPHARMA", "Healthcare"),
    ("TCS", "Information Technology"),
    ("TATACONSUM", "Fast Moving Consumer Goods"),
    ("TMPV", "Automobile and Auto Components"),
    ("TATASTEEL", "Metals & Mining"),
    ("TECHM", "Information Technology"),
    ("TITAN", "Consumer Durables"),
    ("TRENT", "Consumer Services"),
    ("ULTRACEMCO", "Construction Materials"),
    ("WIPRO", "Information Technology"),
]

# Quick symbol -> sector lookup for Nifty 50 names (avoids a slow yfinance
# .info call for the names we already know).
NIFTY_50_SECTORS = {sym: sector for sym, sector in NIFTY_50}

# Official NSE Indices constituent CSV files (public, no auth required).
# Used to dynamically build Nifty 100 / 200 / 500 so the app never relies on
# a stale hardcoded list for the larger universes.
INDEX_CSV_URLS = {
    "Nifty 50": "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
    "Nifty 100": "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
    "Nifty 200": "https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv",
    "Nifty 500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
}

# Optional local override: if this file exists next to app.py, its contents
# take priority over both the hardcoded list and the live fetch, per universe.
# Format: {"Nifty 200": ["RELIANCE", "TCS", ...], "Nifty 500": [...]}
UNIVERSE_JSON_OVERRIDE = Path(__file__).parent / "universes.json"

UNIVERSE_CHOICES = ["Nifty 50", "Nifty 100", "Nifty 200", "Nifty 500"]
DEFAULT_UNIVERSE = "Nifty 200"

NSE_SUFFIX = ".NS"

# --------------------------------------------------------------------------
# Strategy parameters (Module 2: Overnight Screener)
# --------------------------------------------------------------------------
SMA_FAST = 44
SMA_SLOW = 200
EMA_FAST = 20

SMA_FAST_SLOPE_LOOKBACK = 5     # "44 SMA today > 44 SMA 5 trading days ago"
SMA_SLOW_SLOPE_LOOKBACK = 10    # "200 SMA today > 200 SMA 10 trading days ago"

DEFAULT_PULLBACK_BAND_PCT = 1.5   # Daily close within +/-1.5% of 44 SMA
ATR_PERIOD = 14
RVOL_LOOKBACK = 10
DEFAULT_RVOL_THRESHOLD = 1.0

DAILY_HISTORY_PERIOD = "1y"       # enough bars for a 200 SMA + slope lookback
MIN_BARS_REQUIRED = SMA_SLOW + SMA_SLOW_SLOPE_LOOKBACK + 5

# --------------------------------------------------------------------------
# Strategy parameters (Module 3: Intraday Tracker)
# --------------------------------------------------------------------------
INTRADAY_PERIOD = "5d"
INTRADAY_INTERVAL = "5m"

# The brief doesn't give a numeric band for "touches or dips near" the 44 SMA
# intraday (only the daily 1.5% pullback band in Module 2 is specified).
# This is treated as a separate, configurable assumption -- default 0.3%,
# adjustable from the sidebar.
DEFAULT_INTRADAY_PROXIMITY_PCT = 0.3
INVALIDATION_MULTIPLIER = 2.0  # "decisively broken" = past 2x the proximity band

# --------------------------------------------------------------------------
# Risk management defaults (Module 4)
# --------------------------------------------------------------------------
DEFAULT_CAPITAL = 10_000.0
DEFAULT_RISK_PCT = 1.0
DEFAULT_LEVERAGE = 5
DEFAULT_RR_TARGETS = (1.5, 2.0)

# --------------------------------------------------------------------------
# Market hours (Asia/Kolkata) -- informational only, does not gate the UI
# --------------------------------------------------------------------------
MARKET_TZ = "Asia/Kolkata"
MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE = 9, 15
MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE = 15, 30

# --------------------------------------------------------------------------
# Cache TTLs (seconds)
# --------------------------------------------------------------------------
TTL_UNIVERSE = 24 * 60 * 60   # index constituent list: 1 day
TTL_DAILY = 30 * 60           # daily OHLCV: 30 minutes
TTL_INTRADAY = 60             # 5-min OHLCV: 1 minute

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,text/plain,*/*",
}
