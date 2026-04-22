"""Borrow fee (cost-to-borrow, CTB) lookups via iborrowdesk.com.

iborrowdesk exposes a free public API backed by IBKR data updated every
~15 minutes during market hours. We use it to enrich ticker rows with:

- borrow_fee: latest annualized % fee (float, e.g. 0.25 or 53.2)
- borrow_shares_available: how many shares are currently lendable
- htb: bool, "hard to borrow" if fee >= 5% OR very low availability

Why this matters for squeeze detection:
- Borrow fee = supply/demand price of short-selling that name
- High fees mean shorts are paying real money daily just to stay short,
  which creates forced-cover pressure if the stock rallies
- GME was 50%+ before the 2021 squeeze; everyday large-caps are 0.25%
"""
from __future__ import annotations

import concurrent.futures
import time
from typing import Iterable

import requests

_BASE = "https://iborrowdesk.com/api/ticker/"
_HEADERS = {"User-Agent": "squeeze-radar/1.0"}
_TIMEOUT = 6


def _fetch_one(ticker: str) -> dict:
    """Return latest {fee, available} for one ticker. Empty dict on failure."""
    try:
        r = requests.get(_BASE + ticker.upper(), headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code != 200:
            return {}
        data = r.json()
    except Exception:
        return {}

    daily = data.get("daily") or []
    if not daily:
        return {}
    # iborrowdesk sorts ascending by date, so the last entry is newest
    latest = daily[-1]
    fee = latest.get("fee")
    avail = latest.get("available")

    try:
        fee_f = float(fee) if fee is not None else None
    except (TypeError, ValueError):
        fee_f = None
    try:
        avail_f = float(avail) if avail is not None else None
    except (TypeError, ValueError):
        avail_f = None

    if fee_f is None and avail_f is None:
        return {}
    return {
        "borrow_fee": fee_f,
        "borrow_shares_available": avail_f,
        "htb": _is_htb(fee_f, avail_f),
    }


def _is_htb(fee, avail) -> bool:
    """Hard-to-borrow when fee is elevated or availability is thin."""
    if fee is not None and fee >= 5.0:
        return True
    if avail is not None and avail <= 50_000:
        return True
    return False


def fetch_borrow_fees(tickers: Iterable[str], max_workers: int = 8) -> dict:
    """Fetch borrow info for many tickers in parallel.

    Returns a dict mapping uppercase ticker -> {borrow_fee, borrow_shares_available, htb}.
    Missing tickers are simply absent from the result.
    """
    tickers = list({t.upper() for t in tickers if t})
    out: dict = {}
    if not tickers:
        return out

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in tickers}
        for fut in concurrent.futures.as_completed(futures):
            t = futures[fut]
            try:
                r = fut.result()
            except Exception:
                r = {}
            if r:
                out[t] = r
    return out
