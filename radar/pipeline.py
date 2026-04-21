"""End-to-end pipeline: social chatter → fundamentals → scoring → ranking."""
from __future__ import annotations

import pandas as pd

from .fundamentals import build_fundamentals_table
from .history import load_aggregate
from .scoring import rank_tickers, early_movers
from .social import build_social_table
from .trend import compute_trends


# Filter tickers that look like real equity tickers (avoid junk from Reddit parsing)
def _looks_like_ticker(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if not (1 <= len(s) <= 6):
        return False
    if not s.replace("-", "").replace(".", "").isalpha():
        return False
    return s.isupper()


# Obvious false positives that show up in Reddit posts as ALL CAPS words
BLACKLIST = {
    "DD", "CEO", "CFO", "IPO", "SEC", "USA", "FDA", "EOD", "EOW", "AI",
    "USD", "EUR", "TLDR", "YOLO", "FOMO", "ATH", "ATL", "BTD", "WSB",
    "PDF", "ETF", "IRS", "IRA", "API", "GDP", "CPI", "PPI", "FOMC", "FED",
    "ELON", "PUT", "CALL", "LONG", "SHORT", "NEW", "OLD", "HOLD", "BUY",
    "SELL", "GAIN", "LOSS", "BULL", "BEAR", "PUMP", "DUMP", "MOON", "RIP",
    "OR", "ON", "IS", "IT", "BE", "TO", "AT", "AS", "AN", "BY", "DO", "GO",
    "IF", "IN", "NO", "OF", "SO", "UP", "US", "WE", "FOR", "ALL", "ANY",
    "ARE", "CAN", "GET", "HAS", "HAD", "HE", "HER", "HIM", "HIS", "HOW",
    "ITS", "MAY", "NOW", "OUR", "OUT", "SEE", "SHE", "THE", "TOO", "WAS",
    "WAY", "WHO", "WHY", "YES", "YOU", "YOUR", "JUST", "LIKE", "MAKE",
    "MUCH", "ONLY", "OVER", "SOME", "SUCH", "THAN", "THAT", "THEM", "THEN",
    "WITH", "WHAT", "WHEN", "WILL", "WORK", "EVEN", "EVER", "BEEN", "FROM",
    "HAVE", "HERE", "INTO", "LESS", "MORE", "MOST", "MUST", "NEED", "NEXT",
    "ONCE", "SEEN", "SURE", "TAKE", "THIS", "USER", "VERY", "WANT", "WELL",
    "WERE", "YEAR", "OPEN", "HIGH", "LOW", "RED", "GREEN",
}


def build_ranked_universe(
    max_candidates: int = 40,
    enrich_sentiment_top: int = 15,
    progress_cb=None,
) -> dict:
    """Full pipeline. Returns {'all': DataFrame, 'top': DataFrame, 'early': DataFrame}.

    Steps:
      1) Pull social chatter (Reddit via ApeWisdom + Stocktwits trending)
      2) Pick the top `max_candidates` by chatter
      3) Enrich each with yfinance fundamentals + options + price action
      4) Score and rank
      5) Derive early-movers view
    """
    social = build_social_table(enrich_sentiment_top=enrich_sentiment_top)
    if social.empty:
        return {"all": pd.DataFrame(), "top": pd.DataFrame(), "early": pd.DataFrame()}

    # Clean ticker list
    social = social[social["ticker"].apply(_looks_like_ticker)]
    social = social[~social["ticker"].isin(BLACKLIST)]

    # Rank candidates by combined chatter signal
    social["chatter_rank_score"] = (
        social.get("reddit_mentions", 0).fillna(0).rank(pct=True) * 60
        + social.get("reddit_velocity", 1).fillna(1).rank(pct=True) * 25
        + (31 - social.get("st_rank", 31).fillna(31)) / 30 * 15
    )
    candidates = (
        social.sort_values("chatter_rank_score", ascending=False)
        .head(max_candidates)["ticker"]
        .tolist()
    )

    # Enrich with yfinance data
    fund = build_fundamentals_table(candidates, progress_cb=progress_cb)

    # Merge social + fundamentals
    merged = fund.merge(social, on="ticker", how="left")

    # Rank
    ranked = rank_tickers(merged)

    # ---- Multi-day trend bonus ---------------------------------------------
    # Pull the rolling history and compute per-ticker climber metrics. Apply a
    # bonus to Squeeze Score for sustained accelerators (caps at +10).
    history = load_aggregate()
    trends = compute_trends(history)
    if not trends.empty:
        trend_cols = [
            "ticker", "days_tracked", "days_in_top20",
            "rising_streak", "mention_slope", "score_slope", "climber_score",
        ]
        ranked = ranked.merge(
            trends[trend_cols], on="ticker", how="left"
        )
        # Bonus: up to +10 pts from climber_score (100 -> +10)
        bonus = (ranked["climber_score"].fillna(0) / 100 * 10).clip(lower=0, upper=10)
        ranked["squeeze_score"] = (ranked["squeeze_score"] + bonus).clip(upper=100)
        ranked["trend_bonus"] = bonus.round(1)
        ranked = ranked.sort_values("squeeze_score", ascending=False).reset_index(drop=True)
    else:
        ranked["trend_bonus"] = 0.0

    # Climbers view: sustained accelerators (high climber_score)
    climbers = pd.DataFrame()
    if not trends.empty:
        climbers = (
            ranked[ranked.get("climber_score", 0).fillna(0) >= 40]
            .sort_values("climber_score", ascending=False)
            .reset_index(drop=True)
        )

    # Never let the early-movers view crash the main pipeline.
    try:
        early = early_movers(ranked)
    except Exception:
        early = pd.DataFrame()

    top = ranked.head(25)
    return {
        "all": ranked,
        "top": top,
        "early": early,
        "climbers": climbers,
        "trends": trends,
        "history": history,
    }
