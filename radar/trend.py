"""Multi-day chatter trend analytics.

Given the rolling history aggregate, compute per-ticker trend metrics that
capture *sustained* acceleration (the real pre-pump pattern) rather than
one-day spikes (often just news reactions that fade).

Key metrics per ticker:
    days_tracked       — how many distinct UTC days we've seen it
    days_in_top20      — days it appeared in the top 20 by Squeeze Score
    rising_streak      — consecutive days mention velocity has been >= 1.0
    mention_slope      — slope of log-mentions vs. day index (OLS)
    score_slope        — same but for Squeeze Score
    climber_score      — composite 0-100: rewards sustained acceleration
"""
from __future__ import annotations

from datetime import timezone

import numpy as np
import pandas as pd


def _daily(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse intraday snapshots to one row per ticker per UTC day (latest)."""
    if df.empty:
        return df
    d = df.copy()
    d["day"] = d["scanned_at"].dt.tz_convert("UTC").dt.date
    # Take the latest snapshot per (ticker, day)
    d = d.sort_values("scanned_at").groupby(["ticker", "day"], as_index=False).tail(1)
    return d


def _slope(y: pd.Series) -> float:
    """OLS slope of y vs. 0..n-1. NaN-safe."""
    y = pd.Series(y).astype(float).dropna()
    n = len(y)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    # Simple closed-form slope
    x_mean = x.mean()
    y_mean = y.mean()
    denom = ((x - x_mean) ** 2).sum()
    if denom == 0:
        return 0.0
    return float(((x - x_mean) * (y - y_mean)).sum() / denom)


def _streak(values: pd.Series, threshold: float = 1.0) -> int:
    """Longest consecutive-from-the-end run where value >= threshold."""
    v = values.astype(float).fillna(0).tolist()
    run = 0
    for x in reversed(v):
        if x >= threshold:
            run += 1
        else:
            break
    return run


def compute_trends(history: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Per-ticker trend metrics across the loaded history.

    `top_n` controls what counts as "in the top" for the days_in_top_N metric.
    """
    if history.empty:
        return pd.DataFrame(
            columns=[
                "ticker", "days_tracked", "days_in_top20", "rising_streak",
                "mention_slope", "score_slope", "climber_score",
            ]
        )

    daily = _daily(history)

    # Flag top-N membership per day
    daily["is_top_n"] = (
        daily.groupby("day")["squeeze_score"]
        .rank(method="min", ascending=False)
        <= top_n
    )

    rows = []
    for tkr, g in daily.sort_values("day").groupby("ticker", sort=False):
        mentions = g["reddit_mentions"].fillna(0)
        velocity = g["reddit_velocity"].fillna(0) if "reddit_velocity" in g else pd.Series(dtype=float)
        scores = g["squeeze_score"].fillna(0) if "squeeze_score" in g else pd.Series(dtype=float)

        rows.append({
            "ticker": tkr,
            "days_tracked": int(g["day"].nunique()),
            "days_in_top20": int(g["is_top_n"].sum()),
            "rising_streak": _streak(velocity, threshold=1.0),
            "mention_slope": _slope(np.log1p(mentions)),
            "score_slope": _slope(scores),
            "last_mentions": int(mentions.iloc[-1]) if len(mentions) else 0,
            "last_score": float(scores.iloc[-1]) if len(scores) else 0.0,
        })

    trends = pd.DataFrame(rows)
    if trends.empty:
        return trends

    # Composite climber_score: rewards consistency + positive slope + rising streak
    def _clip(x, lo=0, hi=100):
        return max(lo, min(hi, x))

    def _climber(r) -> float:
        s = 0.0
        # Days in top-20 — cap at 10 days = 35 pts
        s += _clip(r["days_in_top20"] / 10 * 35, 0, 35)
        # Rising streak — 4+ consecutive days = 25 pts
        s += _clip(r["rising_streak"] / 4 * 25, 0, 25)
        # Mention slope — positive trajectory
        s += _clip(r["mention_slope"] * 20, 0, 25)
        # Score slope — composite already-rising
        s += _clip(r["score_slope"] * 2, 0, 15)
        return round(s, 1)

    trends["climber_score"] = trends.apply(_climber, axis=1)
    trends = trends.sort_values("climber_score", ascending=False).reset_index(drop=True)
    return trends


def ticker_timeline(history: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Return daily timeline for one ticker (for charting in the UI)."""
    if history.empty:
        return pd.DataFrame()
    d = _daily(history)
    out = d[d["ticker"] == ticker].sort_values("day")
    return out
