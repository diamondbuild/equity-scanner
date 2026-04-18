"""Social chatter signals — ApeWisdom (Reddit aggregator) + Stocktwits trending.

ApeWisdom tracks ticker mentions across WSB, r/stocks, r/options, r/SPACs,
r/investing, r/daytrading, 4chan/biz, and gives 24h-ago rank & mentions so we
get velocity for free. No API key needed.

Stocktwits exposes a public trending-symbols endpoint with watchlist counts
and sentiment proxies.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (squeeze-radar)"}
TIMEOUT = 12

# ---------------------------------------------------------------- ApeWisdom --
APEWISDOM_BASE = "https://apewisdom.io/api/v1.0/filter"

# Aggregator filters we care about. "all-stocks" rolls up every stock sub.
APEWISDOM_FILTERS = {
    "all_stocks": "all-stocks",
    "wsb": "wallstreetbets",
    "options": "options",
    "stocks": "stocks",
    "daytrading": "Daytrading",
    "spacs": "SPACs",
    "wsb_elite": "WallStreetbetsELITE",
}


def _fetch_apewisdom(filter_name: str, max_pages: int = 2) -> list[dict]:
    """Return a list of ticker records for one ApeWisdom filter."""
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        url = f"{APEWISDOM_BASE}/{filter_name}/page/{page}"
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception:
            break
        out.extend(data.get("results", []))
        if page >= data.get("pages", 1):
            break
        time.sleep(0.2)
    return out


def fetch_reddit_chatter() -> pd.DataFrame:
    """Combined Reddit view across subs. One row per ticker with mention metrics."""
    frames = []
    for label, filt in APEWISDOM_FILTERS.items():
        rows = _fetch_apewisdom(filt, max_pages=2)
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["source"] = label
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True)
    for c in ("mentions", "upvotes", "rank", "rank_24h_ago", "mentions_24h_ago"):
        if c in raw.columns:
            raw[c] = pd.to_numeric(raw[c], errors="coerce")

    # Aggregate per ticker across all subs
    agg = (
        raw.groupby("ticker", as_index=False)
        .agg(
            name=("name", "first"),
            reddit_mentions=("mentions", "sum"),
            reddit_upvotes=("upvotes", "sum"),
            reddit_mentions_24h_ago=("mentions_24h_ago", "sum"),
            reddit_best_rank=("rank", "min"),
            reddit_sources=("source", lambda s: ",".join(sorted(set(s)))),
        )
    )

    # Velocity: today's mentions vs 24h ago. >1 means rising.
    agg["reddit_velocity"] = (
        (agg["reddit_mentions"] + 1) / (agg["reddit_mentions_24h_ago"] + 1)
    )
    return agg


# ---------------------------------------------------------------- Stocktwits -
STOCKTWITS_TRENDING = "https://api.stocktwits.com/api/2/trending/symbols.json"
STOCKTWITS_SENTIMENT = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"


def fetch_stocktwits_trending() -> pd.DataFrame:
    """Top ~30 trending symbols on Stocktwits. Watchlist count = popularity proxy."""
    try:
        r = requests.get(STOCKTWITS_TRENDING, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        syms = r.json().get("symbols", [])
    except Exception:
        return pd.DataFrame()

    rows = []
    for i, s in enumerate(syms):
        sym = s.get("symbol", "")
        # Skip crypto (tickers like BTC.X) — we only trade equities here
        if "." in sym:
            continue
        rows.append(
            {
                "ticker": sym,
                "st_title": s.get("title"),
                "st_rank": i + 1,                      # 1 = most trending
                "st_watchlist": s.get("watchlist_count") or 0,
            }
        )
    return pd.DataFrame(rows)


def fetch_stocktwits_sentiment(symbol: str) -> dict | None:
    """Recent messages for one ticker → crude bullish/bearish tag ratio.

    Stocktwits users self-label messages Bullish or Bearish. Not sentiment-perfect,
    but it's honest signal from committed posters.
    """
    try:
        r = requests.get(
            STOCKTWITS_SENTIMENT.format(symbol=symbol),
            headers=UA,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        msgs = r.json().get("messages", [])
    except Exception:
        return None

    bull = bear = 0
    for m in msgs:
        ent = (m.get("entities") or {}).get("sentiment") or {}
        basic = ent.get("basic")
        if basic == "Bullish":
            bull += 1
        elif basic == "Bearish":
            bear += 1

    total_tagged = bull + bear
    if total_tagged == 0:
        return {"st_msgs": len(msgs), "st_bull": 0, "st_bear": 0, "st_bull_pct": None}
    return {
        "st_msgs": len(msgs),
        "st_bull": bull,
        "st_bear": bear,
        "st_bull_pct": bull / total_tagged * 100,
    }


# ------------------------------------------------------------ Combined view --
def build_social_table(enrich_sentiment_top: int = 15) -> pd.DataFrame:
    """Merge Reddit chatter + Stocktwits trending into one table.

    Enriches only the top N Reddit tickers with Stocktwits per-symbol sentiment
    (that endpoint is slow — 15 is a reasonable budget).
    """
    reddit = fetch_reddit_chatter()
    st_trend = fetch_stocktwits_trending()

    if reddit.empty and st_trend.empty:
        return pd.DataFrame()

    if reddit.empty:
        merged = st_trend
    elif st_trend.empty:
        merged = reddit
    else:
        merged = reddit.merge(st_trend, on="ticker", how="outer")

    # Mentioned on both platforms → true cross-platform heat
    merged["on_both"] = (
        merged.get("reddit_mentions", pd.Series(0)).fillna(0).gt(0)
        & merged.get("st_rank", pd.Series(0)).fillna(0).gt(0)
    )

    # Enrich sentiment for top Reddit names (keeps API load bounded)
    if "reddit_mentions" in merged.columns and enrich_sentiment_top > 0:
        top = merged.sort_values("reddit_mentions", ascending=False, na_position="last")
        top = top.head(enrich_sentiment_top)
        extras = []
        for tkr in top["ticker"]:
            s = fetch_stocktwits_sentiment(tkr)
            if s:
                s["ticker"] = tkr
                extras.append(s)
            time.sleep(0.1)
        if extras:
            merged = merged.merge(pd.DataFrame(extras), on="ticker", how="left")

    return merged
