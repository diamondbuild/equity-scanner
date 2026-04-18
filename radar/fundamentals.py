"""Squeeze fundamentals + options pressure + price confirmation.

All three pulled from yfinance to avoid extra API keys. yfinance short interest
is updated ~twice a month (FINRA cycle) which is fine — these structural metrics
don't change intraday.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf


def _safe(info: dict, key: str, default=None):
    v = info.get(key)
    if v is None:
        return default
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return default
    return v


def fetch_snapshot(symbol: str) -> dict:
    """One ticker → squeeze fundamentals + options + price metrics.

    Returns a flat dict. Any missing field is None — downstream handles it.
    """
    out: dict = {"ticker": symbol}
    try:
        tk = yf.Ticker(symbol)
        info = tk.info or {}
    except Exception:
        return out

    # -------- Squeeze fundamentals --------
    shares_short = _safe(info, "sharesShort")
    float_shares = _safe(info, "floatShares")
    shares_out = _safe(info, "sharesOutstanding")
    short_pct_float = _safe(info, "shortPercentOfFloat")      # decimal (0.15 = 15%)
    short_pct_out = _safe(info, "sharesPercentSharesOut")     # decimal
    days_to_cover = _safe(info, "shortRatio")                 # days (short/avg_daily_vol)

    # yfinance sometimes reports short_pct as decimal, sometimes as percent.
    # Normalize to percent.
    def _to_pct(v):
        if v is None:
            return None
        return v * 100 if v < 1 else v

    out.update({
        "company": _safe(info, "shortName") or _safe(info, "longName"),
        "sector": _safe(info, "sector"),
        "price": _safe(info, "currentPrice") or _safe(info, "regularMarketPrice"),
        "market_cap": _safe(info, "marketCap"),
        "float_shares": float_shares,
        "shares_out": shares_out,
        "shares_short": shares_short,
        "short_pct_float": _to_pct(short_pct_float),
        "short_pct_out": _to_pct(short_pct_out),
        "days_to_cover": days_to_cover,
        "avg_vol_10d": _safe(info, "averageDailyVolume10Day"),
        "avg_vol_3m": _safe(info, "averageVolume"),
    })

    # -------- Price action: recent bars --------
    try:
        hist = tk.history(period="3mo", interval="1d", auto_adjust=False)
    except Exception:
        hist = pd.DataFrame()

    if not hist.empty and len(hist) >= 6:
        close = hist["Close"]
        vol = hist["Volume"]
        out["chg_1d_%"] = float((close.iloc[-1] / close.iloc[-2] - 1) * 100)
        if len(close) >= 6:
            out["chg_5d_%"] = float((close.iloc[-1] / close.iloc[-6] - 1) * 100)
        if len(close) >= 21:
            out["chg_20d_%"] = float((close.iloc[-1] / close.iloc[-21] - 1) * 100)
        # Volume vs 20-day avg
        if len(vol) >= 21:
            avg20 = vol.iloc[-21:-1].mean()
            if avg20 > 0:
                out["vol_ratio_20"] = float(vol.iloc[-1] / avg20)
        # Distance from trailing high
        look = min(len(hist), 252)
        high = hist["High"].iloc[-look:].max()
        if high > 0:
            out["dist_hi_%"] = float((close.iloc[-1] / high - 1) * 100)

    # -------- Options pressure --------
    call_vol = put_vol = 0
    try:
        exps = tk.options[:3]  # nearest 3 expirations — bulk of activity
        for exp in exps:
            oc = tk.option_chain(exp)
            call_vol += int(oc.calls["volume"].fillna(0).sum())
            put_vol += int(oc.puts["volume"].fillna(0).sum())
    except Exception:
        pass

    out["call_vol"] = call_vol
    out["put_vol"] = put_vol
    if put_vol > 0:
        out["call_put_ratio"] = call_vol / put_vol
    elif call_vol > 0:
        out["call_put_ratio"] = float("inf")
    else:
        out["call_put_ratio"] = None

    # "Unusual" options: total option volume vs 10-day avg stock volume as a
    # rough proxy (no free options-volume history on yfinance)
    if call_vol and out.get("avg_vol_10d"):
        out["opt_activity_ratio"] = call_vol / max(out["avg_vol_10d"], 1) * 100

    return out


def build_fundamentals_table(tickers: list[str], progress_cb=None) -> pd.DataFrame:
    """Fetch snapshots for a list of tickers. `progress_cb(done, total)` optional."""
    rows = []
    total = len(tickers)
    for i, t in enumerate(tickers):
        rows.append(fetch_snapshot(t))
        if progress_cb:
            progress_cb(i + 1, total)
    return pd.DataFrame(rows)
