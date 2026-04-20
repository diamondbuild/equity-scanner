"""Combine social + fundamentals + options + price into a Squeeze Score.

Each component is normalized to 0–100 and then weighted. Transparent on purpose —
the UI shows every component so you can see WHY something ranks high.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


WEIGHTS = {
    "social": 0.35,
    "squeeze": 0.30,
    "options": 0.20,
    "price": 0.15,
}


def _clip(x, lo=0, hi=100):
    return max(lo, min(hi, x))


# ------------------------------------------------------------ Component: social
def social_score(row) -> float:
    """0-100 from Reddit mention volume + velocity + Stocktwits presence/sentiment."""
    score = 0.0

    # Raw mention volume (log-scaled — 1000+ mentions shouldn't be 100x a 10-mention name)
    m = row.get("reddit_mentions") or 0
    if m > 0:
        score += _clip(np.log1p(m) / np.log1p(500) * 50, 0, 50)  # caps at 50 pts

    # Velocity — ratio of today vs 24h ago mentions. 2.0 = doubling, 5.0 = parabolic.
    v = row.get("reddit_velocity")
    if v and not pd.isna(v):
        # v in [1, 5] → [0, 25], clipped
        score += _clip((v - 1) / 4 * 25, 0, 25)

    # Stocktwits trending rank (1 = hottest)
    st_rank = row.get("st_rank")
    if st_rank and not pd.isna(st_rank):
        # rank 1 → 15 pts, rank 30 → 1 pt
        score += _clip((31 - st_rank) / 30 * 15, 0, 15)

    # Bullish ratio from Stocktwits tagged messages
    bull = row.get("st_bull_pct")
    if bull is not None and not pd.isna(bull):
        # >50% bullish → positive, <50% → penalty
        score += _clip((bull - 50) / 50 * 10, -10, 10)

    return _clip(score, 0, 100)


# ----------------------------------------------------------- Component: squeeze
def squeeze_score(row) -> float:
    """0-100 from short interest % float + days to cover + float tightness."""
    score = 0.0

    sp = row.get("short_pct_float")  # percent
    if sp is not None and not pd.isna(sp):
        # 5% → 10 pts, 15% → 40 pts, 25%+ → 60 pts (hard squeezes usually >20%)
        score += _clip(sp / 25 * 60, 0, 60)

    dtc = row.get("days_to_cover")
    if dtc is not None and not pd.isna(dtc):
        # 2 days → 8 pts, 5 days → 25 pts, 10+ → 30 pts
        score += _clip(dtc / 10 * 30, 0, 30)

    # Small float = easier to squeeze. Below 50M floats get a bonus.
    f = row.get("float_shares")
    if f and f > 0:
        if f < 20_000_000:
            score += 10
        elif f < 50_000_000:
            score += 6
        elif f < 100_000_000:
            score += 3

    return _clip(score, 0, 100)


# ----------------------------------------------------------- Component: options
def options_score(row) -> float:
    """0-100 from call/put ratio + raw call volume + activity vs avg stock volume."""
    score = 0.0

    cpr = row.get("call_put_ratio")
    if cpr is not None and not pd.isna(cpr):
        if cpr == float("inf"):
            score += 30
        else:
            # 1.0 = neutral → 0 pts, 3.0 → 30 pts, 5.0+ → 40 pts
            score += _clip((cpr - 1) / 4 * 40, 0, 40)

    cv = row.get("call_vol") or 0
    if cv > 0:
        # log-scale: 1k calls ~15pts, 10k ~30pts, 100k ~45pts
        score += _clip(np.log10(cv + 1) / 5 * 30, 0, 30)

    ar = row.get("opt_activity_ratio")  # call_vol as % of avg stock vol
    if ar is not None and not pd.isna(ar):
        # 1% → 5pts, 5% → 20pts, 10%+ → 30pts
        score += _clip(ar / 10 * 30, 0, 30)

    return _clip(score, 0, 100)


# ------------------------------------------------------------- Component: price
def price_score(row) -> float:
    """0-100 confirmation that price is already reacting (or setup is tight)."""
    score = 50.0  # start neutral

    c5 = row.get("chg_5d_%")
    if c5 is not None and not pd.isna(c5):
        # +20% over 5d = max bonus, -10% = max penalty
        score += _clip(c5 / 20 * 25, -25, 25)

    vr = row.get("vol_ratio_20")
    if vr is not None and not pd.isna(vr):
        # 2x avg vol = +15, 3x = +25
        score += _clip((vr - 1) * 15, 0, 25)

    return _clip(score, 0, 100)


# ------------------------------------------------------------------ Aggregate
def squeeze_probability(row) -> dict:
    s_soc = social_score(row)
    s_sq = squeeze_score(row)
    s_opt = options_score(row)
    s_prc = price_score(row)
    total = (
        WEIGHTS["social"] * s_soc
        + WEIGHTS["squeeze"] * s_sq
        + WEIGHTS["options"] * s_opt
        + WEIGHTS["price"] * s_prc
    )
    return {
        "score_social": round(s_soc, 1),
        "score_squeeze": round(s_sq, 1),
        "score_options": round(s_opt, 1),
        "score_price": round(s_prc, 1),
        "squeeze_score": round(total, 1),
    }


def rank_tickers(df: pd.DataFrame) -> pd.DataFrame:
    """Add component + total scores, sort desc by squeeze_score."""
    if df.empty:
        return df
    scores = df.apply(lambda r: pd.Series(squeeze_probability(r)), axis=1)
    out = pd.concat([df.reset_index(drop=True), scores.reset_index(drop=True)], axis=1)
    return out.sort_values("squeeze_score", ascending=False).reset_index(drop=True)


# ----------------------------------------------------- Early-movers (pre-pump)
def early_movers(df: pd.DataFrame) -> pd.DataFrame:
    """Social heating up BUT price hasn't caught up yet — potential pre-pump setups.

    Heuristic:
      - social score >= 40 (real chatter)
      - reddit_velocity >= 1.5 (accelerating)
      - chg_5d_% <= 10 (hasn't ripped yet) — skipped if column missing
      - price > 1 (skip pure penny stocks)
    """
    if df.empty or "score_social" not in df.columns:
        return pd.DataFrame()

    def _col(name, default):
        """Return df[name] if present, else a constant Series of `default`."""
        if name in df.columns:
            return df[name].fillna(default)
        return pd.Series(default, index=df.index)

    mask = (
        (_col("score_social", 0) >= 40)
        & (_col("reddit_velocity", 0) >= 1.5)
        & (_col("chg_5d_%", 0) <= 10)
        & (_col("price", 0) > 1)
    )
    return df[mask].sort_values("score_social", ascending=False).reset_index(drop=True)
