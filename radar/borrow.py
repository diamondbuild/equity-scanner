"""Borrow fee (cost-to-borrow) lookups.

Source: companiesmarketcap.com's global "highest cost to borrow" leaderboard,
which is a public page (allowed by their robots.txt) listing the ~top 100
hardest-to-borrow stocks worldwide with their current annualized fee rate.

Why this matters for squeeze detection:
- Cost-to-borrow = supply/demand price of short-selling that name
- High fees (5%+ elevated, 20%+ very elevated, 100%+ extreme) mean shorts
  are paying real money daily just to stay short, which creates forced-cover
  pressure if the stock rallies.
- Any ticker NOT on this leaderboard is inherently a low-fee name (<5%),
  which we treat as "no squeeze pressure from borrow cost".

Design choice: we fetch the leaderboard ONCE per scan (one HTTP call, ~160KB)
and look up every ranked ticker against the result. That's dramatically more
reliable than per-ticker API calls.
"""
from __future__ import annotations

import re
from typing import Iterable

import requests

_BASE_URL = "https://companiesmarketcap.com/companies-with-the-highest-cost-to-borrow/"
# We fetch the top ~N pages (100 rows each). Pages 1-10 cover every ticker
# with a fee ≥ ~5%, which is our HTB threshold. Anything beyond that has
# fees too low to affect squeeze scoring.
_PAGES_TO_FETCH = 10
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = 12


def _parse_leaderboard(html: str) -> dict:
    """Parse the cost-to-borrow leaderboard HTML into {ticker: fee_pct}.

    Only US-listed tickers are retained (no foreign suffixes like .PA or .HK).
    """
    out: dict = {}
    m = re.search(r"<tbody[^>]*>(.*?)</tbody>", html, re.DOTALL)
    if not m:
        return out
    tbody = m.group(1)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.DOTALL)
    for r in rows:
        t = re.search(
            r'<div class="company-code">(?:<[^>]+>)*([^<]+)</div>', r
        )
        if not t:
            continue
        ticker = t.group(1).strip().upper()
        # Skip foreign listings — they don't match our yfinance tickers
        if "." in ticker or not ticker.isalpha() or len(ticker) > 5:
            continue
        # Fee is the second `data-sort` attribute in the row (after the rank)
        sorts = re.findall(r'data-sort="([-0-9\.]+)"', r)
        if len(sorts) < 2:
            continue
        try:
            fee = float(sorts[1])
        except ValueError:
            continue
        if fee <= 0:
            continue
        out[ticker] = fee
    return out


def _page_url(page: int) -> str:
    return _BASE_URL if page <= 1 else f"{_BASE_URL}page/{page}/"


def _fetch_leaderboard(pages: int = _PAGES_TO_FETCH) -> dict:
    """Fetch and parse the top N pages of the leaderboard.

    Returns merged {ticker: fee_pct}. If a ticker appears on multiple pages
    (shouldn't, but defensive), the highest fee wins. Returns {} on total
    failure; partial failures just mean fewer tickers covered.
    """
    merged: dict = {}
    sess = requests.Session()
    sess.headers.update(_HEADERS)
    for p in range(1, pages + 1):
        try:
            r = sess.get(_page_url(p), timeout=_TIMEOUT)
            if r.status_code != 200:
                continue
            page_data = _parse_leaderboard(r.text)
            for t, fee in page_data.items():
                if t not in merged or fee > merged[t]:
                    merged[t] = fee
            # If a page returns nothing, we've hit the end
            if not page_data:
                break
        except Exception:
            continue
    return merged


def _is_htb(fee: float | None) -> bool:
    """Hard-to-borrow when fee is elevated."""
    return fee is not None and fee >= 5.0


def fetch_borrow_fees(tickers: Iterable[str], max_workers: int = 1) -> dict:
    """Return {TICKER: {borrow_fee, htb}} for the requested tickers.

    The leaderboard is fetched once. Tickers NOT on the leaderboard are
    absent from the result (they're implicitly <5% fee). The `max_workers`
    arg is accepted for API compatibility with the old parallel version,
    but unused — we only make one HTTP call.
    """
    board = _fetch_leaderboard()
    if not board:
        return {}
    out: dict = {}
    for t in tickers:
        if not isinstance(t, str):
            continue
        key = t.upper()
        fee = board.get(key)
        if fee is not None:
            out[key] = {"borrow_fee": fee, "htb": _is_htb(fee)}
    return out
