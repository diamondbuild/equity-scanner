"""Squeeze Radar — social-sentiment-driven short-squeeze/bull-run scanner.

Pulls ticker chatter from ApeWisdom (WSB + other subs) and Stocktwits, enriches
with yfinance fundamentals + options + price action, and ranks by a composite
Squeeze Score.

iPhone-friendly layout. No API keys required.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from radar.pipeline import build_ranked_universe

# --------------------------------------------------------------- Page config --
st.set_page_config(
    page_title="Squeeze Radar",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.1rem; padding-bottom: 2rem; }
      .stButton > button { padding: 0.6rem 1rem; font-size: 1rem; }
      [data-testid="stMetricValue"] { font-size: 1.4rem; }
      [data-testid="stDataFrame"] { -webkit-overflow-scrolling: touch; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🚀 Squeeze Radar")
st.caption("Daily short-squeeze / bull-run candidates · Reddit + Stocktwits + options flow")


# -------------------------------------------------------------------- Sidebar
with st.sidebar:
    st.header("Scan settings")
    max_candidates = st.slider(
        "Tickers to deep-scan",
        min_value=15,
        max_value=60,
        value=35,
        step=5,
        help="How many of the top-chatter tickers to enrich with fundamentals + options. "
             "More = slower. 35 is a good daily default.",
    )
    sentiment_top = st.slider(
        "Tickers to pull Stocktwits sentiment for",
        min_value=0,
        max_value=30,
        value=15,
        step=5,
        help="Per-ticker sentiment is slow. Limit how many to enrich.",
    )
    st.divider()
    st.markdown(
        "**How it works**\n\n"
        "1. Pull trending tickers from ApeWisdom (WSB + r/stocks + r/options + r/SPACs) "
        "and Stocktwits.\n"
        "2. For the top N, pull short interest, days-to-cover, float, options flow, "
        "and recent price action from Yahoo.\n"
        "3. Score each on 4 dimensions and combine into a 0-100 **Squeeze Score**."
    )
    st.caption(f"Components: Social 35% · Squeeze 30% · Options 20% · Price 15%")


# ------------------------------------------------------------------- Run scan
@st.cache_data(show_spinner=False, ttl=1800)  # 30-min cache
def _cached_run(max_candidates: int, sentiment_top: int) -> dict:
    return build_ranked_universe(
        max_candidates=max_candidates,
        enrich_sentiment_top=sentiment_top,
    )


top_btn, refresh_btn, ts_col = st.columns([1, 1, 2])
with top_btn:
    run = st.button("🔍 Run scan", type="primary", use_container_width=True)
with refresh_btn:
    if st.button("♻️ Force refresh", use_container_width=True):
        _cached_run.clear()
        run = True
with ts_col:
    st.caption(f"Now: {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")

if "results" not in st.session_state:
    st.session_state.results = None

if run:
    prog = st.progress(0.0, text="Pulling social chatter…")

    def _cb(done, total):
        prog.progress(done / max(total, 1), text=f"Enriching {done}/{total} tickers…")

    # We re-run through cache but pass a dummy progress so first call shows motion
    try:
        # Streamlit's cache doesn't run the callback when cached — re-route
        from radar.pipeline import build_ranked_universe as _build
        st.session_state.results = _build(
            max_candidates=max_candidates,
            enrich_sentiment_top=sentiment_top,
            progress_cb=_cb,
        )
        # Also warm the cache for the non-progress path
        _cached_run.clear()
    finally:
        prog.empty()

results = st.session_state.results

if not results:
    st.info("Tap **Run scan** to pull today's list. Takes ~30-90 seconds.")
    st.stop()

top = results["top"]
early = results["early"]
all_ranked = results["all"]

if top.empty:
    st.error("No data returned. Try again in a minute — source APIs may be rate-limiting.")
    st.stop()


# ------------------------------------------------------------------- Top cards
st.subheader("🔥 Top squeeze candidates")
top5 = top.head(5)
cols = st.columns(min(len(top5), 5))
for col, (_, row) in zip(cols, top5.iterrows()):
    with col:
        score = row["squeeze_score"]
        color = "🟢" if score >= 60 else "🟡" if score >= 40 else "⚪"
        st.metric(
            f"{color} {row['ticker']}",
            f"{score:.0f}",
            delta=f"{row.get('chg_1d_%', 0):+.1f}% today" if pd.notna(row.get("chg_1d_%")) else None,
        )
        sp = row.get("short_pct_float")
        if pd.notna(sp):
            st.caption(f"Short: {sp:.1f}% of float")


# --------------------------------------------------------------------- Tabs
tab_top, tab_early, tab_detail, tab_all = st.tabs(
    ["Top 25", "🌱 Early movers", "Ticker detail", "Full list"]
)


def _format_df(df: pd.DataFrame, compact: bool) -> pd.DataFrame:
    if df.empty:
        return df
    compact_cols = [
        "ticker", "squeeze_score", "price", "chg_1d_%", "short_pct_float",
        "call_put_ratio", "reddit_mentions", "reddit_velocity",
    ]
    full_cols = [
        "ticker", "squeeze_score",
        "score_social", "score_squeeze", "score_options", "score_price",
        "price", "chg_1d_%", "chg_5d_%", "vol_ratio_20",
        "short_pct_float", "days_to_cover", "float_shares",
        "call_vol", "put_vol", "call_put_ratio",
        "reddit_mentions", "reddit_velocity", "reddit_sources",
        "st_rank", "st_bull_pct",
    ]
    cols = compact_cols if compact else full_cols
    cols = [c for c in cols if c in df.columns]
    return df[cols]


def _style(view: pd.DataFrame):
    fmt = {
        "squeeze_score": "{:.0f}",
        "score_social": "{:.0f}",
        "score_squeeze": "{:.0f}",
        "score_options": "{:.0f}",
        "score_price": "{:.0f}",
        "price": "${:,.2f}",
        "chg_1d_%": "{:+.2f}",
        "chg_5d_%": "{:+.2f}",
        "vol_ratio_20": "{:.2f}x",
        "short_pct_float": "{:.1f}%",
        "days_to_cover": "{:.1f}",
        "float_shares": "{:,.0f}",
        "call_vol": "{:,.0f}",
        "put_vol": "{:,.0f}",
        "call_put_ratio": "{:.2f}",
        "reddit_mentions": "{:,.0f}",
        "reddit_velocity": "{:.2f}x",
        "st_rank": "{:.0f}",
        "st_bull_pct": "{:.0f}%",
    }
    fmt = {k: v for k, v in fmt.items() if k in view.columns}
    styled = view.style.format(fmt, na_rep="—")
    if "squeeze_score" in view.columns:
        styled = styled.background_gradient(
            subset=["squeeze_score"], cmap="RdYlGn", vmin=0, vmax=100
        )
    return styled


with tab_top:
    compact = st.toggle("Compact view", value=True, key="compact_top")
    view = _format_df(top, compact)
    st.dataframe(_style(view), use_container_width=True, height=560)
    st.download_button(
        "⬇️ CSV",
        top.to_csv(index=False),
        file_name=f"squeeze_top_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

with tab_early:
    st.caption(
        "Social heating up, price hasn't run yet. Higher risk, higher potential for "
        "catching the move before the crowd."
    )
    if early.empty:
        st.info("No early-mover setups matching the filter right now.")
    else:
        compact_e = st.toggle("Compact view", value=True, key="compact_early")
        st.dataframe(_style(_format_df(early, compact_e)), use_container_width=True, height=440)

with tab_detail:
    if top.empty:
        st.info("Run a scan first.")
    else:
        sym = st.selectbox("Ticker", top["ticker"].tolist())
        row = top[top["ticker"] == sym].iloc[0]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Squeeze Score", f"{row['squeeze_score']:.0f}/100")
        c2.metric("Social", f"{row['score_social']:.0f}")
        c3.metric("Squeeze setup", f"{row['score_squeeze']:.0f}")
        c4.metric("Options", f"{row['score_options']:.0f}")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Price", f"${row['price']:,.2f}" if pd.notna(row.get("price")) else "—")
        c6.metric("1d chg", f"{row['chg_1d_%']:+.2f}%" if pd.notna(row.get("chg_1d_%")) else "—")
        c7.metric(
            "Short % float",
            f"{row['short_pct_float']:.1f}%" if pd.notna(row.get("short_pct_float")) else "—",
        )
        c8.metric(
            "C/P ratio",
            f"{row['call_put_ratio']:.2f}" if pd.notna(row.get("call_put_ratio")) else "—",
        )

        # Candlestick
        try:
            hist = yf.Ticker(sym).history(period="3mo", interval="1d")
            if not hist.empty:
                fig = go.Figure(
                    data=[
                        go.Candlestick(
                            x=hist.index,
                            open=hist["Open"],
                            high=hist["High"],
                            low=hist["Low"],
                            close=hist["Close"],
                            name=sym,
                        )
                    ]
                )
                fig.update_layout(
                    height=380,
                    margin=dict(l=6, r=6, t=30, b=6),
                    xaxis_rangeslider_visible=False,
                    title=f"{sym} · 3mo daily",
                )
                st.plotly_chart(fig, use_container_width=True)
        except Exception:
            st.warning("Couldn't load chart.")

        st.markdown("**Chatter context**")
        srcs = row.get("reddit_sources") or "—"
        st.write(
            f"Reddit sources seen on: **{srcs}**  \n"
            f"Reddit mentions (24h): **{row.get('reddit_mentions', '—')}** · "
            f"velocity: **{row.get('reddit_velocity', 0):.2f}x**  \n"
            f"Stocktwits trending rank: **{row.get('st_rank', '—')}** · "
            f"bullish tag %: **{row.get('st_bull_pct', '—')}**"
        )

with tab_all:
    compact_a = st.toggle("Compact view", value=False, key="compact_all")
    st.dataframe(_style(_format_df(all_ranked, compact_a)), use_container_width=True, height=560)

# --------------------------------------------------------------------- Footer
st.divider()
st.caption(
    "Not financial advice. yfinance short interest updates ~twice a month (FINRA cycle). "
    "Options data is delayed. Stocktwits sentiment reflects self-tagged posts only."
)
