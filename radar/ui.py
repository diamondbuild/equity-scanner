"""Custom table renderer with a pro-trader-terminal aesthetic.

Builds HTML directly rather than relying on pandas Styler. Every cell is
shaped by a small renderer function so we can embed bars, chips, arrows,
sparklines, etc. \u2014 much closer to a modern enterprise app than Streamlit's
default tables.

Design tokens:
    bg       #0B0F1A   (app background)
    surface  #141A29   (card / table bg)
    border   #1F2937
    text     #E5E7EB
    muted    #7A8699
    accent   #A3E635   (lime \u2014 pro trader)
    warn     #F59E0B
    danger   #EF4444
    good     #34D399
"""
from __future__ import annotations

import html
import math
from typing import Callable

import pandas as pd

# -------------------------------------------------------------------- Tokens -
BG = "#0B0F1A"
SURFACE = "#141A29"
SURFACE_HOVER = "#1A2237"
BORDER = "#1F2937"
TEXT = "#E5E7EB"
MUTED = "#7A8699"
ACCENT = "#A3E635"
WARN = "#F59E0B"
DANGER = "#EF4444"
GOOD = "#34D399"


# ------------------------------------------------------------- Cell renderers -
def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


def cell_score_bar(v, vmin: float = 0, vmax: float = 100) -> str:
    """Big primary score rendered as number + horizontal bar."""
    if not _is_num(v):
        return f'<span class="muted">\u2014</span>'
    pct = max(0, min(100, (v - vmin) / (vmax - vmin) * 100))
    # Color ramp by score level
    if v >= 70:
        color = ACCENT
    elif v >= 50:
        color = "#EAB308"  # amber
    elif v >= 30:
        color = "#F59E0B"
    else:
        color = MUTED
    return (
        f'<div class="score-cell">'
        f'  <span class="score-num">{v:.0f}</span>'
        f'  <div class="score-track"><div class="score-fill" '
        f'style="width:{pct:.0f}%;background:{color}"></div></div>'
        f'</div>'
    )


def cell_component_bars(row: dict) -> str:
    """Stack of 4 mini vertical bars: social / squeeze / options / price."""
    keys = [("score_social", "S"), ("score_squeeze", "Q"), ("score_options", "O"), ("score_price", "P")]
    bars = []
    for k, label in keys:
        v = row.get(k)
        if not _is_num(v):
            h = 0
            color = MUTED
        else:
            h = max(2, int(v))          # visible minimum
            # All component bars use accent \u2014 height is the story, not color
            color = ACCENT if v >= 60 else "#64748B"
        bars.append(
            f'<div class="cbar-wrap" title="{label}: {v if _is_num(v) else "n/a"}">'
            f'  <div class="cbar" style="height:{h}%;background:{color}"></div>'
            f'  <span class="cbar-label">{label}</span>'
            f'</div>'
        )
    return f'<div class="comp-bars">{"".join(bars)}</div>'


def cell_short_chip(v) -> str:
    if not _is_num(v):
        return '<span class="muted">\u2014</span>'
    if v >= 30:
        cls = "chip chip-danger"
    elif v >= 15:
        cls = "chip chip-warn"
    else:
        cls = "chip chip-muted"
    return f'<span class="{cls}">{v:.0f}%</span>'


def cell_pct_change(v) -> str:
    if not _is_num(v):
        return '<span class="muted">\u2014</span>'
    if v > 0:
        arrow, color = "\u2191", GOOD
    elif v < 0:
        arrow, color = "\u2193", DANGER
    else:
        arrow, color = "\u00b7", MUTED
    return f'<span class="num" style="color:{color}">{arrow} {abs(v):.2f}%</span>'


def cell_velocity(v) -> str:
    """Reddit velocity (ratio of today's mentions vs 24h ago)."""
    if not _is_num(v):
        return '<span class="muted">\u2014</span>'
    if v >= 2.0:
        cls, icon = "chip chip-accent", "\u2191\u2191"
    elif v >= 1.3:
        cls, icon = "chip chip-good", "\u2191"
    elif v >= 0.9:
        cls, icon = "chip chip-muted", "\u00b7"
    else:
        cls, icon = "chip chip-muted", "\u2193"
    return f'<span class="{cls}">{icon} {v:.1f}x</span>'


def cell_call_put(v) -> str:
    if not _is_num(v):
        return '<span class="muted">\u2014</span>'
    if v == float("inf"):
        return '<span class="chip chip-accent">puts: 0</span>'
    if v >= 3:
        cls = "chip chip-accent"
    elif v >= 1.5:
        cls = "chip chip-good"
    elif v <= 0.7:
        cls = "chip chip-danger"
    else:
        cls = "chip chip-muted"
    return f'<span class="{cls}">{v:.2f}</span>'


def cell_signals(row: dict) -> str:
    """Which signals are firing for this ticker? Small row of chips."""
    chips = []
    if _is_num(row.get("reddit_mentions")) and row["reddit_mentions"] >= 50:
        chips.append('<span class="chip chip-muted">WSB</span>')
    if _is_num(row.get("st_rank")) and row["st_rank"] <= 20:
        chips.append('<span class="chip chip-muted">ST</span>')
    if _is_num(row.get("call_put_ratio")) and (row["call_put_ratio"] == float("inf") or row["call_put_ratio"] >= 2):
        chips.append('<span class="chip chip-accent">C/P</span>')
    if _is_num(row.get("short_pct_float")) and row["short_pct_float"] >= 20:
        chips.append('<span class="chip chip-danger">SHORT</span>')
    if _is_num(row.get("rising_streak")) and row["rising_streak"] >= 3:
        chips.append(f'<span class="chip chip-accent">\u2191{int(row["rising_streak"])}d</span>')
    inner = " ".join(chips) if chips else '<span class="muted">\u2014</span>'
    return f'<div class="sig-row">{inner}</div>'


def cell_price(v) -> str:
    if not _is_num(v):
        return '<span class="muted">\u2014</span>'
    return f'<span class="num">${v:,.2f}</span>'


def cell_num(v, fmt: str = "{:,.0f}") -> str:
    if not _is_num(v):
        return '<span class="muted">\u2014</span>'
    return f'<span class="num">{fmt.format(v)}</span>'


def cell_ticker(v, company=None) -> str:
    t = html.escape(str(v)) if v is not None else ""
    # company may be NaN (float), None, or a string — normalize safely
    if company is None or (isinstance(company, float) and company != company):
        sub = ""
    else:
        c = str(company).strip()
        sub = f'<span class="ticker-sub">{html.escape(c)[:20]}</span>' if c and c.lower() != "nan" else ""
    return f'<div class="ticker-cell"><span class="ticker-sym">{t}</span>{sub}</div>'


# --------------------------------------------------------------- Column defs -
# Each entry maps a column key to (label, renderer). Renderer is called with
# either a single value (when it needs just one field) or the whole row dict
# (when it aggregates multiple fields).
def _render_value(key: str, row: dict):
    v = row.get(key)
    if key == "squeeze_score":
        return cell_score_bar(v)
    if key == "components":
        return cell_component_bars(row)
    if key == "short_pct_float":
        return cell_short_chip(v)
    if key in ("chg_1d_%", "chg_5d_%", "chg_20d_%"):
        return cell_pct_change(v)
    if key == "reddit_velocity":
        return cell_velocity(v)
    if key == "call_put_ratio":
        return cell_call_put(v)
    if key == "signals":
        return cell_signals(row)
    if key == "price":
        return cell_price(v)
    if key == "ticker":
        return cell_ticker(v, row.get("company"))
    if key == "reddit_mentions":
        return cell_num(v, "{:,.0f}")
    if key == "vol_ratio_20":
        return cell_num(v, "{:.2f}x")
    if key == "days_to_cover":
        return cell_num(v, "{:.1f}")
    if key == "climber_score":
        return cell_score_bar(v)
    if key == "rising_streak":
        return cell_num(v, "{:.0f}d")
    if key == "days_in_top20":
        return cell_num(v, "{:.0f}")
    if key == "trend_bonus":
        return cell_num(v, "+{:.1f}")
    if key == "call_vol" or key == "put_vol" or key == "float_shares":
        return cell_num(v, "{:,.0f}")
    if key == "st_rank":
        return cell_num(v, "{:.0f}")
    if key == "st_bull_pct":
        return cell_num(v, "{:.0f}%")
    if key == "score_social" or key == "score_squeeze" or key == "score_options" or key == "score_price":
        return cell_num(v, "{:.0f}")
    # default
    if isinstance(v, float):
        if v != v:  # NaN
            return '<span class="muted">\u2014</span>'
        return cell_num(v, "{:,.2f}")
    if v is None:
        return '<span class="muted">\u2014</span>'
    return html.escape(str(v))


COL_LABELS = {
    "ticker": "Ticker",
    "squeeze_score": "Score",
    "components": "Breakdown",
    "signals": "Signals",
    "short_pct_float": "Short",
    "chg_1d_%": "1D",
    "chg_5d_%": "5D",
    "chg_20d_%": "20D",
    "reddit_velocity": "Velocity",
    "call_put_ratio": "C/P",
    "price": "Price",
    "reddit_mentions": "Mentions",
    "vol_ratio_20": "Vol \u00d7",
    "days_to_cover": "DTC",
    "climber_score": "Climber",
    "rising_streak": "Streak",
    "days_in_top20": "Days\u00a0Top20",
    "trend_bonus": "Bonus",
    "call_vol": "Calls",
    "put_vol": "Puts",
    "float_shares": "Float",
    "st_rank": "ST #",
    "st_bull_pct": "Bull%",
    "score_social": "Social",
    "score_squeeze": "Squeeze",
    "score_options": "Options",
    "score_price": "Price\u00a0S",
}


# --------------------------------------------------------------- CSS payload -
TABLE_CSS = f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap');

  /* App-wide typography + background bleed */
  html, body, [class*="css"], .stMarkdown, .stApp {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  }}
  .stApp {{ background: {BG}; }}

  /* Table container */
  .prot-wrap {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    overflow: hidden;
    margin: 4px 0 12px 0;
  }}
  .prot-scroll {{
    overflow-x: auto;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    max-height: 600px;
  }}
  table.prot {{
    border-collapse: separate;
    border-spacing: 0;
    width: 100%;
    color: {TEXT};
    font-size: 0.86rem;
  }}
  table.prot thead th {{
    position: sticky; top: 0;
    background: {SURFACE};
    color: {MUTED};
    font-weight: 500;
    font-size: 0.72rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    padding: 10px 12px;
    border-bottom: 1px solid {BORDER};
    white-space: nowrap;
    text-align: right;
    z-index: 3;
  }}
  table.prot tbody td {{
    padding: 10px 12px;
    border-bottom: 1px solid {BORDER};
    white-space: nowrap;
    vertical-align: middle;
    text-align: right;
  }}
  table.prot tbody tr:last-child td {{ border-bottom: none; }}
  table.prot tbody tr:hover td {{ background: {SURFACE_HOVER}; }}

  /* First column (ticker) frozen */
  table.prot th:first-child, table.prot td:first-child {{
    position: sticky; left: 0;
    background: {SURFACE};
    z-index: 2;
    text-align: left;
    border-right: 1px solid {BORDER};
    min-width: 92px;
  }}
  table.prot tbody tr:hover td:first-child {{ background: {SURFACE_HOVER}; }}
  table.prot thead th:first-child {{ z-index: 4; text-align: left; }}

  /* Ticker cell */
  .ticker-cell {{ display: flex; flex-direction: column; gap: 1px; }}
  .ticker-sym {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-weight: 700;
    font-size: 0.98rem;
    color: {TEXT};
    letter-spacing: 0.02em;
  }}
  .ticker-sub {{ font-size: 0.7rem; color: {MUTED}; }}

  .num {{ font-family: 'JetBrains Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums; }}
  .muted {{ color: {MUTED}; }}

  /* Score cell \u2014 number + bar below */
  .score-cell {{ display: flex; flex-direction: column; align-items: flex-end; gap: 4px; min-width: 64px; }}
  .score-num {{ font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 1rem; color: {TEXT}; }}
  .score-track {{ width: 60px; height: 4px; background: {BORDER}; border-radius: 2px; overflow: hidden; }}
  .score-fill {{ height: 100%; border-radius: 2px; transition: width 200ms; }}

  /* Component bars */
  .comp-bars {{ display: inline-flex; gap: 3px; align-items: flex-end; height: 32px; }}
  .cbar-wrap {{ display: flex; flex-direction: column; align-items: center; width: 12px; height: 100%; }}
  .cbar {{ width: 100%; background: {ACCENT}; border-radius: 2px 2px 0 0; min-height: 2px; }}
  .cbar-label {{ font-size: 0.6rem; color: {MUTED}; margin-top: 2px; }}
  .cbar-wrap {{ justify-content: flex-end; }}

  /* Chips */
  .chip {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.02em;
  }}
  .chip-muted  {{ background: rgba(122,134,153,0.12); color: {MUTED}; }}
  .chip-accent {{ background: rgba(163,230,53,0.12);  color: {ACCENT}; }}
  .chip-good   {{ background: rgba(52,211,153,0.12);  color: {GOOD}; }}
  .chip-warn   {{ background: rgba(245,158,11,0.12);  color: {WARN}; }}
  .chip-danger {{ background: rgba(239,68,68,0.12);   color: {DANGER}; }}
  .sig-row .chip {{ margin-right: 4px; }}
</style>
"""


# ------------------------------------------------------------- Public renderer
def render_table(
    df: pd.DataFrame,
    columns: list[str] | None = None,
    *,
    sort_by: str | None = None,
) -> str:
    """Return HTML for a pro-styled table. Caller wraps in st.markdown(html, unsafe_allow_html=True)."""
    if df.empty:
        return f'<div class="prot-wrap" style="padding:24px;color:{MUTED};">No rows.</div>'

    df = df.copy()
    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=False)

    # Columns to render \u2014 only include ones we can compute. Always keep `ticker` first.
    if columns is None:
        columns = [
            "ticker", "squeeze_score", "components", "signals",
            "short_pct_float", "reddit_velocity", "call_put_ratio",
            "price", "chg_1d_%", "chg_5d_%", "reddit_mentions", "vol_ratio_20",
        ]
    # Drop columns we can't produce (e.g. trend fields missing on early runs)
    available = set(df.columns) | {"components", "signals"}  # computed columns
    columns = [c for c in columns if c in available]
    if "ticker" in columns:
        columns = ["ticker"] + [c for c in columns if c != "ticker"]

    # Header row
    head = "".join(
        f'<th>{COL_LABELS.get(c, c)}</th>' for c in columns
    )
    # Body rows
    body_rows = []
    for _, r in df.iterrows():
        row = r.to_dict()
        cells = "".join(f"<td>{_render_value(c, row)}</td>" for c in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    body = "".join(body_rows)

    return (
        f'<div class="prot-wrap"><div class="prot-scroll">'
        f'<table class="prot"><thead><tr>{head}</tr></thead>'
        f'<tbody>{body}</tbody></table>'
        f'</div></div>'
    )


def inject_css() -> str:
    """Return the table CSS so callers can inject it once per page load."""
    return TABLE_CSS
