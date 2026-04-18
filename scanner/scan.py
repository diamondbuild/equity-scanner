"""Top-level scan orchestration: fetch bars + compute metrics table."""
from __future__ import annotations

import pandas as pd

from .data import BarRequest, fetch_history
from .signals import compute_row


def run_scan(
    symbols: list[str],
    period: str = "3mo",
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch history for a universe and build a metrics DataFrame, one row per symbol."""
    req = BarRequest(symbols=tuple(sorted(set(symbols))), period=period, interval=interval)
    bars = fetch_history(req)
    rows = [compute_row(sym, df) for sym, df in bars.items() if not df.empty]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("symbol").reset_index(drop=True)
    return df


# Filter presets that users can toggle in the UI
PRESETS = {
    "Breakouts (near 52W high)": lambda df: df[
        (df["dist_52wH_%"].fillna(-999) >= -3.0)
        & (df["vol_ratio_20"].fillna(0) >= 1.2)
    ],
    "Momentum (5d winners)": lambda df: df[
        (df["chg_5d_%"].fillna(-999) >= 5.0)
        & (df["trend_20_50"] == "bull")
    ],
    "Oversold bounce setup": lambda df: df[
        (df["rsi_14"].fillna(50) <= 30)
        & (df["chg_1d_%"].fillna(0) >= 0)
    ],
    "Overbought (RSI > 70)": lambda df: df[df["rsi_14"].fillna(0) >= 70],
    "Volume spikes": lambda df: df[df["vol_ratio_20"].fillna(0) >= 2.0],
    "Gap ups (>2%)": lambda df: df[df["gap_%"].fillna(0) >= 2.0],
    "Gap downs (<-2%)": lambda df: df[df["gap_%"].fillna(0) <= -2.0],
    "High volatility (ATR% > 3)": lambda df: df[df["atr_%"].fillna(0) >= 3.0],
}
