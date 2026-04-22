"""End-to-end pipeline: social chatter → fundamentals → scoring → ranking."""
from __future__ import annotations

import pandas as pd

from .borrow import fetch_borrow_fees
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

    # ---- Borrow fee enrichment ---------------------------------------------
    # Look up cost-to-borrow for the top-ranked tickers from the
    # companiesmarketcap.com leaderboard of the 100 hardest-to-borrow stocks
    # globally. Any ticker not on that list has fee < ~5%, which we treat as
    # no squeeze pressure from borrow cost. A single HTTP call covers all
    # tickers. Pre-create columns so the UI always has them.
    # Use numeric NaN (not None) so the column is float dtype from the start —
    # prevents object-dtype propagation that caused '>' int/str sort errors.
    ranked["borrow_fee"] = pd.Series([float("nan")] * len(ranked), dtype="float64")
    ranked["htb"] = False
    ranked["borrow_bonus"] = 0.0
    borrow_meta = {"ok": False, "leaderboard_size": 0, "matched": 0, "error": None}
    try:
        # Only look up tickers that might actually be on the leaderboard:
        # focus on top-ranked candidates and any early-mover-ish names.
        check_tickers = ranked.head(60)["ticker"].tolist()
        if progress_cb:
            progress_cb(0.85, "Checking borrow fees...")
        from .borrow import _fetch_leaderboard
        board = _fetch_leaderboard()
        borrow_meta["leaderboard_size"] = len(board)
        borrow = {}
        if board:
            for t in check_tickers:
                if not isinstance(t, str):
                    continue
                key = t.upper()
                fee = board.get(key)
                if fee is not None:
                    borrow[key] = {"borrow_fee": fee, "htb": fee >= 5.0}
        borrow_meta["matched"] = len(borrow)
        borrow_meta["ok"] = bool(board)
        if borrow:
            ranked["borrow_fee"] = pd.to_numeric(
                ranked["ticker"].map(
                    lambda t: borrow.get(t.upper() if isinstance(t, str) else t, {}).get("borrow_fee")
                ),
                errors="coerce",
            )
            ranked["htb"] = ranked["ticker"].map(
                lambda t: bool(borrow.get(t.upper() if isinstance(t, str) else t, {}).get("htb"))
            )
            # Squeeze bonus from borrow fee
            def _borrow_bonus(fee):
                if fee is None or fee != fee:
                    return 0.0
                try:
                    f = float(fee)
                except (TypeError, ValueError):
                    return 0.0
                if f >= 100:
                    return 15.0
                if f >= 20:
                    return 10.0
                if f >= 5:
                    return 5.0
                return 0.0
            b_bonus = ranked["borrow_fee"].apply(_borrow_bonus)
            b_bonus = pd.to_numeric(b_bonus, errors="coerce").fillna(0.0)
            ranked["borrow_bonus"] = b_bonus
            # Force numeric on sub-scores before arithmetic to avoid object-dtype
            # propagating a '>' int/str comparison error downstream.
            ss_num = pd.to_numeric(ranked["score_squeeze"], errors="coerce").fillna(0)
            ranked["score_squeeze"] = (ss_num + b_bonus).clip(upper=100)
            # Recompute total with updated squeeze component
            from .scoring import WEIGHTS
            soc = pd.to_numeric(ranked["score_social"], errors="coerce").fillna(0)
            sq = pd.to_numeric(ranked["score_squeeze"], errors="coerce").fillna(0)
            opt = pd.to_numeric(ranked["score_options"], errors="coerce").fillna(0)
            prc = pd.to_numeric(ranked["score_price"], errors="coerce").fillna(0)
            ranked["squeeze_score"] = (
                WEIGHTS["social"] * soc
                + WEIGHTS["squeeze"] * sq
                + WEIGHTS["options"] * opt
                + WEIGHTS["price"] * prc
            ).round(1)
    except Exception as e:
        # Never let a borrow-fee hiccup break the full scan
        borrow_meta["error"] = str(e)[:200]

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
        "borrow_meta": borrow_meta,
    }
