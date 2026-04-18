# 🚀 Squeeze Radar

Daily ranked list of stocks with the highest probability of a **short squeeze or bull run**, driven by social sentiment + fundamentals.

Built for buying **calls, LEAPs, or shares** on emerging retail-driven moves.

## What it does

Every run pulls **trending ticker chatter** from:

- **r/wallstreetbets, r/stocks, r/options, r/SPACs, r/investing, r/daytrading, r/WallStreetbetsELITE** — via the [ApeWisdom](https://apewisdom.io/api/) aggregator (mentions + 24h velocity baked in)
- **Stocktwits** — trending symbols + bullish/bearish message ratio

...then for the top ~35 tickers by chatter, enriches with:

- **Short interest** (% of float), days-to-cover, float size
- **Options flow** — call/put volume ratio across the nearest 3 expirations, unusual call activity
- **Price action** — 1d / 5d / 20d moves, volume ratio, distance from highs

Every ticker gets scored on 4 dimensions and combined into a **0–100 Squeeze Score**:

| Component | Weight | What it measures |
|---|---|---|
| **Social** | 35% | Mention volume (log), velocity (today vs 24h ago), Stocktwits rank, bullish tag % |
| **Squeeze setup** | 30% | Short % of float, days-to-cover, float tightness |
| **Options** | 20% | Call/put ratio, call volume, options activity vs avg stock volume |
| **Price** | 15% | 5d momentum + volume ratio (already-moving confirmation) |

## Two views

- **🔥 Top 25** — highest Squeeze Score. Already heating up.
- **🌱 Early movers** — social heating up but price hasn't run yet. Pre-pump setups (higher risk, higher edge).

## Live URL

Deployed on Streamlit Cloud — add to iPhone home screen for app-like access.

## Local run

```bash
git clone https://github.com/diamondbuild/equity-scanner
cd equity-scanner
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Project layout

```
equity-scanner/
├── app.py                     # Streamlit UI
├── requirements.txt
├── radar/
│   ├── social.py              # ApeWisdom + Stocktwits
│   ├── fundamentals.py        # yfinance short interest / options / price
│   ├── scoring.py             # 4-component scoring model
│   └── pipeline.py            # Orchestrator + ticker cleanup/blacklist
└── .streamlit/config.toml     # Dark theme
```

## Why this combination works

Real short squeezes need three things to coincide:
1. **A crowd** willing to pile in (social chatter + velocity)
2. **Shorts to squeeze** (high short % float, tight float)
3. **Option dealers forced to hedge** (heavy call buying → gamma squeeze dynamics)

Each of those is a separate signal in the score, and tickers that light up on all three are the real candidates. Price confirmation keeps us honest that something's actually moving.

## Caveats

- yfinance short interest updates ~twice a month (FINRA cycle) — treat it as structural, not real-time.
- Options volume is delayed.
- Stocktwits bullish/bearish tags are self-reported by posters.
- ApeWisdom is free but can occasionally be rate-limited; retry if a scan returns empty.

## Future upgrades worth considering

- Telegram alert at market open with the top 10 (you already have that infra)
- [Unusual Whales](https://unusualwhales.com/) API integration for real dark-pool + flow data (paid)
- Historical signal tracking to backtest which score cutoffs actually predicted moves
- Pre-market gap scanner that intersects with the squeeze list
