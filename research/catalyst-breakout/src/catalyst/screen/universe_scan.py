"""Stage-A price-only universe scan -> distressed watchlist (Module 1, cheap pass).

The full Module 1 screen needs market cap + fundamentals (per-ticker, expensive).
This pass uses ONLY prices -- which we can get for the whole universe in one
grouped-daily sweep -- to find names that were distressed AND liquid at some point
in the window. That cuts ~10k names to a few hundred, which is the only set worth
spending per-ticker API budget on (fundamentals, market cap, EDGAR catalysts).

A ticker qualifies if, on any day with enough history, it was both:
  * distressed: close <= (1 - min_drawdown) * trailing-252-day high, OR within
    within_pct_of_52w_low of its trailing-252 low, and
  * liquid: trailing avg daily dollar volume >= floor.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..store.db import Database
from config.defaults import Config, DEFAULTS

TRADING_YEAR = 252


@dataclass
class WatchEntry:
    ticker: str
    max_drawdown: float
    first_qualified: str
    avg_dollar_vol: float


def scan(db: Database, cfg: Config = DEFAULTS, min_history: int = 60) -> list[WatchEntry]:
    s = cfg.screen
    tickers = [r["ticker"] for r in db.execute(
        "SELECT DISTINCT ticker FROM prices", ())]
    out: list[WatchEntry] = []
    for t in tickers:
        bars = db.execute(
            "SELECT date, close, volume FROM prices WHERE ticker = ? ORDER BY date ASC",
            (t,),
        )
        if len(bars) < min_history:
            continue
        closes = [b["close"] for b in bars]
        vols = [(b["close"] or 0) * (b["volume"] or 0) for b in bars]
        best_dd = 0.0
        first_qual = None
        qual_adv = 0.0
        for i in range(min_history, len(bars)):
            window = closes[max(0, i - TRADING_YEAR):i + 1]
            hi, lo = max(window), min(window)
            px = closes[i]
            if not hi or px is None:
                continue
            dd = (hi - px) / hi
            near_low = lo > 0 and (px - lo) / lo <= s.within_pct_of_52w_low
            distressed = (dd >= s.min_drawdown_from_52w_high) or near_low
            adv = sum(vols[max(0, i - s.adv_lookback_days):i]) / max(1, min(i, s.adv_lookback_days))
            liquid = adv >= s.min_avg_daily_dollar_volume_usd
            if dd > best_dd:
                best_dd = dd
            if distressed and liquid and first_qual is None:
                first_qual = bars[i]["date"]
                qual_adv = adv
        if first_qual is not None:
            out.append(WatchEntry(t, round(best_dd, 4), first_qual, round(qual_adv, 0)))
    out.sort(key=lambda w: w.max_drawdown, reverse=True)
    return out
