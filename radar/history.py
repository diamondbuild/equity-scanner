"""Scan history store.

Every run appends a compact snapshot to CSV. On Streamlit Cloud (ephemeral disk)
the same snapshot is also committed back to the GitHub repo so history
survives restarts and redeploys.

History layout in the repo:
    history/
      YYYY-MM-DD/
        HHMM.csv            # one full snapshot (top ~40 tickers)
      aggregate.csv         # rolling long-format: (timestamp, ticker, metric, value)

The aggregate.csv is what we read for trend analysis. Individual day files are
kept for debugging and replay.
"""
from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# Columns we persist (keeps files small, avoids bloating the repo)
SNAPSHOT_COLS = [
    "ticker",
    "price",
    "squeeze_score",
    "score_social",
    "score_squeeze",
    "score_options",
    "score_price",
    "reddit_mentions",
    "reddit_velocity",
    "st_rank",
    "st_bull_pct",
    "short_pct_float",
    "days_to_cover",
    "call_put_ratio",
    "call_vol",
    "chg_1d_%",
    "chg_5d_%",
    "vol_ratio_20",
]

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "history"
AGG_PATH = HISTORY_DIR / "aggregate.csv"


# ---------------------------------------------------------------- Local I/O --
def _snapshot_df(ranked: pd.DataFrame, limit: int = 40) -> pd.DataFrame:
    """Slice a ranked scan down to the columns we persist."""
    if ranked.empty:
        return ranked
    df = ranked.head(limit).copy()
    keep = [c for c in SNAPSHOT_COLS if c in df.columns]
    df = df[keep]
    df["scanned_at"] = datetime.now(timezone.utc).isoformat()
    return df


def _write_local(df: pd.DataFrame) -> tuple[Path, Path | None]:
    """Write snapshot + append to aggregate on local disk. Returns (snap_path, agg_path)."""
    now = datetime.now(timezone.utc)
    day_dir = HISTORY_DIR / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    snap_path = day_dir / f"{now.strftime('%H%M')}.csv"
    df.to_csv(snap_path, index=False)

    # Append to aggregate
    AGG_PATH.parent.mkdir(parents=True, exist_ok=True)
    agg_mode = "a" if AGG_PATH.exists() else "w"
    header = not AGG_PATH.exists()
    df.to_csv(AGG_PATH, mode=agg_mode, header=header, index=False)
    return snap_path, AGG_PATH


# ------------------------------------------------- GitHub commit (cloud path) -
def _github_creds() -> tuple[str, str, str] | None:
    """Read GitHub credentials from Streamlit secrets or env. Returns (token, owner, repo) or None."""
    try:
        import streamlit as st
        token = st.secrets.get("GITHUB_TOKEN", None)
        owner = st.secrets.get("GITHUB_OWNER", None) or "diamondbuild"
        repo = st.secrets.get("GITHUB_REPO", None) or "equity-scanner"
    except Exception:
        token = os.environ.get("GITHUB_TOKEN")
        owner = os.environ.get("GITHUB_OWNER", "diamondbuild")
        repo = os.environ.get("GITHUB_REPO", "equity-scanner")

    if not token:
        return None
    return token, owner, repo


def _gh_put_file(
    token: str,
    owner: str,
    repo: str,
    path: str,
    content_bytes: bytes,
    message: str,
) -> bool:
    """Create or update a file via the GitHub contents API. Returns success."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # Check if file exists to get its SHA (needed for update)
    sha = None
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception:
        pass

    payload = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha

    try:
        r = requests.put(url, headers=headers, json=payload, timeout=20)
        return r.status_code in (200, 201)
    except Exception:
        return False


def _fetch_aggregate_from_github() -> pd.DataFrame:
    """Pull the latest aggregate.csv from the GitHub repo (raw URL, no auth needed for public)."""
    creds = _github_creds()
    owner, repo = (creds[1], creds[2]) if creds else ("diamondbuild", "equity-scanner")
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/history/aggregate.csv"
    try:
        return pd.read_csv(url)
    except Exception:
        return pd.DataFrame()


# --------------------------------------------------------------- Public API --
def save_snapshot(ranked: pd.DataFrame, limit: int = 40) -> dict:
    """Persist a scan result. Writes locally, and if a GitHub token is
    configured, also commits to the repo so history survives on cloud.

    Returns a status dict the UI can show.
    """
    snap = _snapshot_df(ranked, limit=limit)
    if snap.empty:
        return {"saved": False, "reason": "empty ranked frame"}

    # Always write local first
    try:
        snap_path, agg_path = _write_local(snap)
    except Exception as e:
        return {"saved": False, "reason": f"local write failed: {e}"}

    # Also push to GitHub if we have creds
    creds = _github_creds()
    gh_result = {"committed": False}
    if creds:
        token, owner, repo = creds
        now = datetime.now(timezone.utc)
        # 1) snapshot file
        snap_rel = f"history/{now.strftime('%Y-%m-%d')}/{now.strftime('%H%M')}.csv"
        snap_bytes = snap.to_csv(index=False).encode()
        ok1 = _gh_put_file(token, owner, repo, snap_rel, snap_bytes,
                           f"scan snapshot {now.strftime('%Y-%m-%d %H:%M UTC')}")

        # 2) aggregate: fetch current, append, push
        current_agg = _fetch_aggregate_from_github()
        if current_agg.empty:
            new_agg = snap
        else:
            new_agg = pd.concat([current_agg, snap], ignore_index=True)
        # Keep only last 90 days to bound file size
        new_agg["scanned_at"] = pd.to_datetime(new_agg["scanned_at"], utc=True, errors="coerce")
        cutoff = now - pd.Timedelta(days=90)
        new_agg = new_agg[new_agg["scanned_at"] >= cutoff]

        agg_bytes = new_agg.to_csv(index=False).encode()
        ok2 = _gh_put_file(token, owner, repo, "history/aggregate.csv", agg_bytes,
                           f"aggregate update {now.strftime('%Y-%m-%d %H:%M UTC')}")
        gh_result = {"committed": ok1 and ok2, "snapshot_ok": ok1, "aggregate_ok": ok2}

    return {
        "saved": True,
        "local_path": str(snap_path),
        "rows": len(snap),
        **gh_result,
    }


def load_aggregate() -> pd.DataFrame:
    """Load the rolling history. Prefers local file; falls back to GitHub raw."""
    if AGG_PATH.exists():
        try:
            df = pd.read_csv(AGG_PATH)
        except Exception:
            df = pd.DataFrame()
    else:
        df = pd.DataFrame()

    if df.empty:
        df = _fetch_aggregate_from_github()

    if not df.empty and "scanned_at" in df.columns:
        df["scanned_at"] = pd.to_datetime(df["scanned_at"], utc=True, errors="coerce")
        df = df.dropna(subset=["scanned_at"])
    return df
