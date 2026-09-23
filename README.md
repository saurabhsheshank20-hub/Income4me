# Nifty Overnight Screener & Intraday Tracker

A Streamlit dashboard for Indian equities (Nifty 50 / 100 / 200 / 500) that:
- screens the daily chart after market close for stocks pulling back to a rising 44/200 SMA trend, and
- tracks those stocks intraday on the 5-minute chart for a VWAP/EMA breakout signal at the level.

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Requires Python 3.10+. `streamlit-autorefresh` is optional (enables the auto-refresh
checkbox on the Intraday Scanner tab) -- everything else still works without it, using
the manual "Refresh Now" button instead.

## File structure

| File | Module in the spec | Responsibility |
|---|---|---|
| `config.py` | -- | Universes, strategy constants, risk defaults, cache TTLs |
| `data_fetcher.py` | 1: Index & Data Ingestion | NSE index constituent lists, yfinance OHLCV, cleaning |
| `indicators.py` | -- | SMA, EMA, Wilder ATR, session VWAP, RVOL (pure pandas) |
| `screener.py` | 2: Overnight Screener | MA alignment/slope, pullback band, RVOL filter |
| `intraday_tracker.py` | 3: Intraday Tracker | 5-min VWAP/EMA signal classification |
| `risk_calculator.py` | 4: Risk Management | Position sizing, margin, R-multiple targets |
| `charts.py` | 5.2: Interactive Charting | Plotly daily & intraday figure builders |
| `app.py` | 5: UI | Streamlit sidebar + 4 tabs wiring everything together |

## Design decisions where the brief left a gap

The spec was precise about most thresholds, but a few things weren't numerically
specified. Each is implemented as a **configurable default in the sidebar**, not a
hardcoded constant, so you can tune it without touching code:

- **Nifty 100/200/500 constituents** are fetched live from NSE Indices' official CSVs
  (`niftyindices.com/IndexConstituent/...`) rather than hardcoded, since these indices
  rebalance semi-annually and a hardcoded ~500-ticker list would silently go stale.
  Nifty 50 is hardcoded (verified against the official list) and doubles as the offline
  fallback if the live fetch fails -- you'll see a visible ⚠️ warning in the sidebar if
  that happens, never a silent substitution. You can also pin your own list by dropping
  a `universes.json` file next to `app.py` (see the comment in `config.py`).
- **RVOL > 1.0** (Module 2) is applied as a hard filter by default, matching the ">"
  condition as written, but can be toggled off from the sidebar if it's over-filtering.
- **"Touches or dips near" the 44 SMA intraday** (Module 3) has no stated tolerance in
  the brief -- unlike Module 2's explicit daily ±1.5% pullback band. A separate,
  smaller intraday proximity band defaults to ±0.3% and is adjustable in the sidebar.
- **A 4th "⚪ Not Near Level" signal state** was added alongside the brief's three
  (🟢/🟡/🔴), for stocks that simply aren't near their support level at all -- without
  it, every stock would be forced into "watching" or "invalidated".
- **Position sizing** cross-checks the risk-based share count against what your
  capital and leverage can actually afford (`capital * leverage / entry price`) and
  caps + flags it if the risk-based number would need more margin than you have. A
  tight stop-loss can otherwise imply a share count you can't actually execute.
- Indicators are hand-implemented on pandas/numpy rather than via `pandas_ta` (which
  has repeatedly broken against modern numpy) -- see the docstring in `indicators.py`.

## Known limitations

- **Not real-time.** Yahoo Finance data via `yfinance` is unofficial and delayed;
  don't treat the Intraday Scanner as a live execution feed.
- **Rate limiting.** Yahoo has no official free API, and `yfinance` is a wrapper
  around undocumented endpoints that do rate-limit. Daily fetches are chunked and
  cached (30 min TTL); intraday fetches are cached for 1 minute. If you scan Nifty 500
  repeatedly in a short window you may still hit limits -- space out full re-screens.
- **NSE endpoint reachability varies by host.** `niftyindices.com` and Yahoo's endpoints
  are sometimes blocked from cloud/datacenter IPs (Streamlit Cloud, some corporate
  networks). The app degrades to the Nifty 50 fallback with a visible warning rather
  than crashing; use the `universes.json` override if this happens consistently on
  your host.
- **No NSE holiday calendar.** The market-open indicator only checks weekday + time
  window (09:15-15:30 IST), not actual NSE trading holidays.
- **Sector labels** are looked up (and cached) only for stocks that already pass every
  other overnight filter, not the whole universe -- `yfinance`'s `.info` call is slow
  enough that fetching it for up to 500 tickers would make the screener impractically
  slow.
- This code was built and unit-tested against synthetic data in a sandboxed
  environment without outbound internet access, so the indicator math, signal logic,
  position sizing, and the full Streamlit control flow were all verified directly --
  but a live run against real Yahoo Finance / NSE endpoints on your machine is the
  first true end-to-end test. Do that before relying on it.

## Disclaimer

For research and education only. This is not investment advice, and nothing here is a
recommendation to buy or sell any security. The screening and signal rules are
rule-based and have not been backtested or validated here -- paper-trade and backtest
before risking real capital.
