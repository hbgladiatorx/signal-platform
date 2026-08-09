"""IV-rank store (Section 6 -- you must build this; Polygon does not provide it).

A daily cron snapshots ATM IV per watchlist name into Supabase (iv_snapshots).
IV rank = percentile of current IV within its trailing window (default 252
trading days). Until >= iv_rank_min_history_days exist for a name, IV rank is
UNRELIABLE and the live engine defers options sizing to a human.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..store.db import Database
from config.defaults import Config, DEFAULTS


def atm_iv_from_chain(chain: list[dict[str, Any]], spot: float) -> float | None:
    """Pick ATM implied vol from a Polygon chain snapshot (closest strike)."""
    best, best_dist = None, float("inf")
    for c in chain:
        details = c.get("details", {})
        strike = details.get("strike_price")
        iv = c.get("implied_volatility")
        if strike is None or iv is None:
            continue
        d = abs(strike - spot)
        if d < best_dist:
            best, best_dist = iv, d
    return best


def snapshot_atm_iv(db: Database, ticker: str, as_of: date, atm_iv: float) -> None:
    db.execute(
        "INSERT OR REPLACE INTO iv_snapshots (ticker, date, atm_iv) VALUES (?, ?, ?)"
        if db.flavor == "sqlite"
        else "INSERT INTO iv_snapshots (ticker, date, atm_iv) VALUES (?, ?, ?) "
             "ON CONFLICT (ticker, date) DO UPDATE SET atm_iv = EXCLUDED.atm_iv",
        (ticker, as_of.isoformat(), atm_iv),
    )


def iv_rank(iv_series: list[float], cfg: Config = DEFAULTS) -> tuple[float | None, bool]:
    """Return (iv_rank_percentile, reliable). iv_series chronological, current last."""
    reliable = len(iv_series) >= cfg.options.iv_rank_min_history_days
    if not iv_series:
        return None, reliable
    window = iv_series[-cfg.options.iv_rank_window_trading_days:]
    cur = window[-1]
    below = sum(1 for v in window if v <= cur)
    return 100.0 * below / len(window), reliable
