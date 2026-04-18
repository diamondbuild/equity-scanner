"""Scanner signals. Each function takes OHLCV DataFrame and returns a scalar
metric (or None) used for ranking/filtering."""
from __future__ import annotations

import numpy as np
import pandas as pd


def pct_change(df: pd.DataFrame, lookback: int = 1) -> float | None:
    if len(df) <= lookback:
        return None
    close = df["close"]
    return float((close.iloc[-1] / close.iloc[-1 - lookback] - 1) * 100)


def volume_ratio(df: pd.DataFrame, window: int = 20) -> float | None:
    """Latest volume / average volume over `window` bars."""
    if len(df) < window + 1:
        return None
    vol = df["volume"]
    avg = vol.iloc[-window - 1 : -1].mean()
    if avg == 0 or pd.isna(avg):
        return None
    return float(vol.iloc[-1] / avg)


def gap_pct(df: pd.DataFrame) -> float | None:
    """Open vs prior close, as percent."""
    if len(df) < 2:
        return None
    prev_close = df["close"].iloc[-2]
    today_open = df["open"].iloc[-1]
    if prev_close == 0 or pd.isna(prev_close):
        return None
    return float((today_open / prev_close - 1) * 100)


def rsi(df: pd.DataFrame, period: int = 14) -> float | None:
    if len(df) < period + 1:
        return None
    close = df["close"]
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    val = rsi_series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def dist_from_52w_high(df: pd.DataFrame) -> float | None:
    """Percent below trailing 252-bar (approx 52 week) high. 0 = at new high."""
    if len(df) < 20:
        return None
    window = min(len(df), 252)
    high = df["high"].iloc[-window:].max()
    last = df["close"].iloc[-1]
    if high == 0 or pd.isna(high):
        return None
    return float((last / high - 1) * 100)


def atr_pct(df: pd.DataFrame, period: int = 14) -> float | None:
    """ATR as a percent of last close — a normalized volatility measure."""
    if len(df) < period + 1:
        return None
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    last = close.iloc[-1]
    if last == 0 or pd.isna(last) or pd.isna(atr):
        return None
    return float(atr / last * 100)


def sma_cross_state(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> str | None:
    """Return 'bull', 'bear', or None. Bull = fast SMA above slow SMA."""
    if len(df) < slow:
        return None
    close = df["close"]
    f = close.rolling(fast).mean().iloc[-1]
    s = close.rolling(slow).mean().iloc[-1]
    if pd.isna(f) or pd.isna(s):
        return None
    return "bull" if f >= s else "bear"


def compute_row(symbol: str, df: pd.DataFrame) -> dict:
    """Compute all scanner metrics for one symbol."""
    last_close = float(df["close"].iloc[-1]) if len(df) else None
    last_vol = int(df["volume"].iloc[-1]) if len(df) else None
    return {
        "symbol": symbol,
        "close": last_close,
        "volume": last_vol,
        "chg_1d_%": pct_change(df, 1),
        "chg_5d_%": pct_change(df, 5),
        "chg_20d_%": pct_change(df, 20),
        "gap_%": gap_pct(df),
        "vol_ratio_20": volume_ratio(df, 20),
        "rsi_14": rsi(df, 14),
        "atr_%": atr_pct(df, 14),
        "dist_52wH_%": dist_from_52w_high(df),
        "trend_20_50": sma_cross_state(df, 20, 50),
    }
