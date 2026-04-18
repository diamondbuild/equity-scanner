"""Data provider layer. Currently wraps yfinance; designed to be swappable.

All public functions return pandas DataFrames with a normalized schema:
    index: DatetimeIndex (timezone-aware, UTC)
    columns: ['open', 'high', 'low', 'close', 'volume']
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import yfinance as yf


@dataclass(frozen=True)
class BarRequest:
    symbols: tuple[str, ...]
    period: str = "3mo"      # yfinance period string
    interval: str = "1d"     # '1m','5m','15m','1h','1d'


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten yfinance output to standard OHLCV column names."""
    if df.empty:
        return df
    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df


def fetch_history(req: BarRequest) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for each symbol. Returns {symbol: DataFrame}."""
    if not req.symbols:
        return {}

    # yfinance handles batches efficiently in one download call
    raw = yf.download(
        tickers=list(req.symbols),
        period=req.period,
        interval=req.interval,
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )

    out: dict[str, pd.DataFrame] = {}
    if raw.empty:
        return out

    # Single symbol: columns are flat
    if len(req.symbols) == 1:
        sym = req.symbols[0]
        out[sym] = _normalize(raw)
        return out

    # Multi symbol: columns are a MultiIndex (symbol, field)
    for sym in req.symbols:
        if sym in raw.columns.get_level_values(0):
            sub = raw[sym].dropna(how="all")
            if not sub.empty:
                out[sym] = _normalize(sub)
    return out


def load_universe(path: str) -> list[str]:
    """Load a ticker list from a text file (one ticker per line)."""
    with open(path) as f:
        return [
            line.strip().upper()
            for line in f
            if line.strip() and not line.startswith("#")
        ]
