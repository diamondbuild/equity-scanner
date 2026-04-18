# Equity / ETF Market Scanner (MVP)

A Streamlit dashboard that scans a universe of equities/ETFs for setups —
breakouts, momentum, volume spikes, gaps, RSI extremes, and volatility.

## Stack

- **Streamlit** — UI
- **yfinance** — free market data (no API key). Swap later for Alpaca / Polygon / Databento.
- **pandas / numpy** — metrics
- **plotly** — candlestick preview

## Project layout

```
equity-scanner/
├── app.py                  # Streamlit entry point
├── requirements.txt
├── scanner/
│   ├── data.py             # Data provider (yfinance wrapper, swappable)
│   ├── signals.py          # Individual metric functions (RSI, ATR%, gap, etc.)
│   └── scan.py             # Orchestrator + preset filters
└── universes/
    ├── sp500_sample.txt    # 50 large caps
    └── etfs_core.txt       # 30 liquid ETFs
```

## Run it

```bash
cd equity-scanner
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
streamlit run app.py
```

Then pick a universe, choose interval/period, and click **Run scan**.

## Metrics computed per symbol

| Column        | Meaning                                           |
|---------------|---------------------------------------------------|
| `chg_1d_%`    | Percent change vs prior bar                       |
| `chg_5d_%`    | Percent change over last 5 bars                   |
| `chg_20d_%`   | Percent change over last 20 bars                  |
| `gap_%`       | Today's open vs prior close                       |
| `vol_ratio_20`| Latest volume / 20-bar average                    |
| `rsi_14`      | 14-period RSI (Wilder's smoothing)                |
| `atr_%`       | ATR(14) as % of last close (normalized vol)       |
| `dist_52wH_%` | % below trailing 252-bar high (0 = new high)      |
| `trend_20_50` | `bull` if SMA20 ≥ SMA50, else `bear`              |

## Preset filters

- **Breakouts** — within 3% of 52W high + volume ≥ 1.2× avg
- **Momentum** — 5-day gain ≥ 5% + bull trend
- **Oversold bounce** — RSI ≤ 30 + positive daily change
- **Overbought** — RSI ≥ 70
- **Volume spikes** — volume ≥ 2× avg
- **Gap up / gap down** — ±2%
- **High volatility** — ATR% ≥ 3

## Extending

- **New data source:** implement the same interface as `scanner/data.py:fetch_history`
  and swap it in `scan.py`. Good upgrade path: Alpaca (free tier, API key).
- **New signals:** add a function to `scanner/signals.py`, wire it into `compute_row`.
- **New preset:** add an entry to `PRESETS` in `scanner/scan.py`.
- **Alerts:** you already have a Telegram pipeline — add a post-scan hook that
  pushes qualifying rows to a channel.

## Known limits of the free data layer

- Yahoo 1-minute bars only go back ~7 days.
- Intraday data is delayed ~15 minutes.
- For live/streaming or survivorship-bias-free history, move to Alpaca / Polygon / Databento.
