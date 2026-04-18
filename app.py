"""Streamlit UI for the equity/ETF market scanner — iPhone-friendly."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from scanner.data import BarRequest, fetch_history, load_universe
from scanner.scan import PRESETS, run_scan

ROOT = Path(__file__).parent
UNIVERSE_DIR = ROOT / "universes"

st.set_page_config(
    page_title="Equity Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",  # phone-friendly
)

# --- Small CSS polish for iPhone ---------------------------------------------
st.markdown(
    """
    <style>
      /* Larger tap targets on primary buttons */
      .stButton > button { padding: 0.6rem 1rem; font-size: 1rem; }
      /* Tighter top padding so the title sits higher on a phone screen */
      .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
      /* Make dataframes scroll smoothly on touch */
      [data-testid="stDataFrame"] { -webkit-overflow-scrolling: touch; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📈 Equity / ETF Scanner")
st.caption("Data: Yahoo Finance · Tap ☰ top-left to open the universe panel")


# ---------- Sidebar: universe + scan params ----------
with st.sidebar:
    st.header("Universe")
    universe_files = sorted(p.name for p in UNIVERSE_DIR.glob("*.txt"))
    choice = st.selectbox(
        "Preset universe",
        ["(custom)"] + universe_files,
        index=1 if universe_files else 0,
    )

    default_tickers = ""
    if choice != "(custom)":
        default_tickers = "\n".join(load_universe(str(UNIVERSE_DIR / choice)))

    tickers_text = st.text_area(
        "Tickers (one per line)",
        value=default_tickers,
        height=180,
        help="Any valid Yahoo ticker (e.g., BRK-B, ^GSPC).",
    )

    st.header("Timeframe")
    interval = st.selectbox(
        "Bar interval",
        ["1d", "1h", "15m", "5m"],
        index=0,
        help="Intraday intervals are limited to recent history by Yahoo.",
    )
    period = st.selectbox(
        "Lookback period",
        ["1mo", "3mo", "6mo", "1y", "2y"],
        index=1,
    )

    run_btn = st.button("🔍 Run scan", type="primary", use_container_width=True)


# ---------- Cached scan so filters don't refetch ----------
@st.cache_data(show_spinner=False, ttl=300)
def cached_scan(symbols: tuple[str, ...], period: str, interval: str) -> pd.DataFrame:
    return run_scan(list(symbols), period=period, interval=interval)


@st.cache_data(show_spinner=False, ttl=300)
def cached_history(symbol: str, period: str, interval: str):
    req = BarRequest(symbols=(symbol,), period=period, interval=interval)
    bars = fetch_history(req)
    return bars.get(symbol)


# ---------- Run scan ----------
tickers = [t.strip().upper() for t in tickers_text.splitlines() if t.strip()]

if "scan_df" not in st.session_state:
    st.session_state.scan_df = pd.DataFrame()

if run_btn:
    if not tickers:
        st.warning("Add at least one ticker.")
    else:
        with st.spinner(f"Scanning {len(tickers)} symbols…"):
            st.session_state.scan_df = cached_scan(tuple(tickers), period, interval)

df = st.session_state.scan_df

if df.empty:
    st.info("Open ☰ (top-left), pick a universe, then tap **Run scan**.")
    st.stop()


# ---------- Filters ----------
st.subheader("Filters")
preset = st.selectbox("Preset filter", ["(none)"] + list(PRESETS.keys()))

c1, c2 = st.columns(2)
with c1:
    min_price = st.number_input("Min price", value=0.0, step=1.0)
with c2:
    min_volume = st.number_input("Min volume", value=0, step=100_000)

c3, c4 = st.columns(2)
with c3:
    trend = st.selectbox("Trend (20/50 SMA)", ["any", "bull", "bear"])
with c4:
    compact = st.toggle("Compact view", value=True, help="Show fewer columns — better on a phone.")

filtered = df.copy()
if preset != "(none)":
    filtered = PRESETS[preset](filtered)
if min_price > 0:
    filtered = filtered[filtered["close"].fillna(0) >= min_price]
if min_volume > 0:
    filtered = filtered[filtered["volume"].fillna(0) >= min_volume]
if trend != "any":
    filtered = filtered[filtered["trend_20_50"] == trend]


# ---------- Results table ----------
st.subheader(f"Results · {len(filtered)} of {len(df)}")

compact_cols = ["symbol", "close", "chg_1d_%", "vol_ratio_20", "rsi_14", "trend_20_50"]
full_cols = [
    "symbol", "close", "volume", "chg_1d_%", "chg_5d_%", "chg_20d_%",
    "gap_%", "vol_ratio_20", "rsi_14", "atr_%", "dist_52wH_%", "trend_20_50",
]
display_cols = compact_cols if compact else full_cols
view = filtered[display_cols].copy()

num_fmt = {
    "close": "{:,.2f}",
    "chg_1d_%": "{:+.2f}",
    "chg_5d_%": "{:+.2f}",
    "chg_20d_%": "{:+.2f}",
    "gap_%": "{:+.2f}",
    "vol_ratio_20": "{:,.2f}",
    "rsi_14": "{:,.1f}",
    "atr_%": "{:,.2f}",
    "dist_52wH_%": "{:+.2f}",
    "volume": "{:,.0f}",
}
fmt = {k: v for k, v in num_fmt.items() if k in view.columns}

styled = view.style.format(fmt)
if "chg_1d_%" in view.columns:
    styled = styled.background_gradient(
        subset=[c for c in ["chg_1d_%", "chg_5d_%", "chg_20d_%"] if c in view.columns],
        cmap="RdYlGn", vmin=-10, vmax=10,
    )
if "rsi_14" in view.columns:
    styled = styled.background_gradient(subset=["rsi_14"], cmap="RdYlGn_r", vmin=20, vmax=80)

st.dataframe(styled, use_container_width=True, height=440)

# CSV export
csv_buf = io.StringIO()
filtered.to_csv(csv_buf, index=False)
st.download_button(
    "⬇️ Download CSV",
    data=csv_buf.getvalue(),
    file_name="scan_results.csv",
    mime="text/csv",
    use_container_width=True,
)


# ---------- Chart preview ----------
st.subheader("Chart preview")
if len(filtered):
    sym = st.selectbox("Symbol", filtered["symbol"].tolist())
    hist = cached_history(sym, period, interval)
    if hist is not None and not hist.empty:
        fig = go.Figure(
            data=[
                go.Candlestick(
                    x=hist.index,
                    open=hist["open"],
                    high=hist["high"],
                    low=hist["low"],
                    close=hist["close"],
                    name=sym,
                )
            ]
        )
        fig.update_layout(
            height=380,  # shorter for portrait phones
            margin=dict(l=6, r=6, t=28, b=6),
            xaxis_rangeslider_visible=False,
            title=f"{sym} · {interval} · {period}",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No history for that symbol.")
