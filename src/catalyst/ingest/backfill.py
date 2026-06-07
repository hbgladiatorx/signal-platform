"""Backfill orchestrator + CLI: provider -> panel, with PIT stamping.

Populates the panel tables the backtester reads (prices, universe, fundamentals,
catalysts). Run this BEFORE the backtest. IV snapshots are forward-only in
practice (historical ATM IV must be reconstructed from per-contract options
aggregates, which is a separate, heavier job) -- see the note below.

Usage:
    python -m catalyst.ingest.backfill --tickers AAPL,MSFT --start 2019-01-01 --end 2024-12-31

Requires POLYGON_API_KEY / FINNHUB_API_KEY in the environment for the
corresponding sources; sources without a key are skipped with a log line.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from typing import Any

from .. import config as config_mod
from ..clients.base import CacheStore, ProviderUnavailable, env_key
from ..clients.polygon import PolygonClient
from ..clients.finnhub import FinnhubClient
from ..clients.edgar import EdgarClient
from ..clients.usaspending import USASpendingClient
from ..store.db import Database
from . import loaders, upsert


def build_clients(cfg) -> dict[str, Any]:
    """Construct only the clients whose keys are present."""
    rt = cfg.runtime
    cache = lambda name: CacheStore(f".cache/{name}", rt.cache_ttl_seconds)  # noqa: E731
    common = dict(max_retries=rt.max_retries, backoff_base=rt.backoff_base_seconds,
                  backoff_max=rt.backoff_max_seconds, user_agent=rt.user_agent)
    clients: dict[str, Any] = {}
    if env_key("POLYGON_API_KEY"):
        clients["polygon"] = PolygonClient(rt.polygon_base_url, api_key=env_key("POLYGON_API_KEY"),
                                           cache=cache("polygon"), **common)
    if env_key("FINNHUB_API_KEY"):
        clients["finnhub"] = FinnhubClient(rt.finnhub_base_url, api_key=env_key("FINNHUB_API_KEY"),
                                           cache=cache("finnhub"), **common)
    # EDGAR needs no key (UA only); USASpending is open.
    clients["edgar"] = EdgarClient(rt.edgar_base_url, cache=cache("edgar"),
                                   submissions_url=rt.edgar_submissions_url, **common)
    clients["usaspending"] = USASpendingClient(rt.usaspending_base_url,
                                               cache=cache("usaspending"), **common)
    return clients


def backfill_prices(db: Database, poly, ticker: str, start: date, end: date) -> int:
    aggs = poly.daily_aggregates(ticker, start, end, adjusted=True)
    return upsert.upsert_prices(db, loaders.prices_from_polygon(ticker, aggs))


def backfill_universe_prices(db: Database, poly, start: date, end: date,
                             progress_every: int = 20) -> dict[str, int]:
    """Full-universe daily prices via grouped-daily: ONE call per trading day,
    every ticker at once (survivorship-correct). Each call is disk-cached, so an
    interrupted run resumes cheaply on re-invocation.
    """
    from datetime import timedelta

    day = start
    rows = days = skipped = 0
    while day <= end:
        if day.weekday() < 5:  # skip weekends; holidays come back empty
            try:
                res = poly.grouped_daily(day, adjusted=True)
                if res:
                    rows += upsert.upsert_prices(db, loaders.prices_from_grouped(day, res))
                    days += 1
                else:
                    skipped += 1
            except ProviderUnavailable:
                skipped += 1
            if (days + skipped) % progress_every == 0:
                print(f"  ...{day.isoformat()}  trading_days={days} rows={rows}", flush=True)
        day += timedelta(days=1)
    return {"trading_days": days, "rows": rows, "empty_days": skipped}


def backfill_universe(db: Database, poly, tickers: list[str], as_of: date) -> int:
    details = []
    for t in tickers:
        try:
            d = poly.ticker_details(t, as_of)
            if d:
                d.setdefault("ticker", t)
                details.append(d)
        except ProviderUnavailable:
            continue
    optionable = set()
    for t in tickers:
        try:
            if poly.options_chain(t, as_of):
                optionable.add(t)
        except ProviderUnavailable:
            continue
    rows = loaders.universe_from_polygon(as_of, details, optionable=optionable)
    return upsert.upsert_universe(db, rows)


def backfill_fundamentals(db: Database, finnhub, ticker: str) -> int:
    payload = finnhub.reported_financials(ticker, freq="quarterly")
    return upsert.upsert_fundamentals(db, loaders.fundamentals_from_finnhub(ticker, payload))


def backfill_catalysts(db: Database, clients: dict[str, Any], ticker: str,
                       start: date, end: date, cik: str | None = None) -> int:
    """Best-effort per source: a failure in one catalyst source must never abort
    the backfill (or suppress the others)."""
    n = 0
    if "finnhub" in clients:
        try:
            surprises = clients["finnhub"].earnings_surprises(ticker)
            n += upsert.upsert_catalysts(db, loaders.catalysts_from_earnings(ticker, surprises))
        except Exception as e:
            print(f"  [{ticker}] earnings catalysts skipped: {type(e).__name__}")
    if cik and "edgar" in clients:
        try:
            forms = ("8-K", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A")
            filings = clients["edgar"].recent_filings(cik, forms, end)
            n += upsert.upsert_catalysts(db, loaders.catalysts_from_edgar(ticker, filings))
        except Exception as e:
            print(f"  [{ticker}] edgar catalysts skipped: {type(e).__name__}")
    if "usaspending" in clients:
        try:
            awards = clients["usaspending"].award_search(ticker, start, end, 0.0)
            n += upsert.upsert_catalysts(db, loaders.catalysts_from_federal(ticker, awards))
        except Exception as e:
            print(f"  [{ticker}] federal catalysts skipped: {type(e).__name__}")
    return n


def run(tickers: list[str], start: date, end: date,
        ciks: dict[str, str] | None = None) -> dict[str, int]:
    cfg = config_mod.load()
    db = Database(cfg.runtime.database_url)
    db.bootstrap()
    clients = build_clients(cfg)

    # Resolve ticker -> CIK from SEC so EDGAR 8-K/13D catalysts can be pulled.
    if ciks is None:
        ciks = {}
        try:
            full = clients["edgar"].ticker_cik_map()
            ciks = {t: full[t] for t in tickers if t in full}
            print(f"resolved CIKs: {ciks}")
        except Exception as e:
            print(f"CIK resolution failed: {type(e).__name__} -> EDGAR catalysts skipped")
    counts = {"prices": 0, "universe": 0, "fundamentals": 0, "catalysts": 0}

    if "polygon" in clients:
        counts["universe"] += backfill_universe(db, clients["polygon"], tickers, end)
        for t in tickers:
            try:
                counts["prices"] += backfill_prices(db, clients["polygon"], t, start, end)
            except ProviderUnavailable:
                pass
    else:
        print("backfill: no POLYGON_API_KEY -> skipping prices + universe")

    if "finnhub" in clients:
        for t in tickers:
            try:
                counts["fundamentals"] += backfill_fundamentals(db, clients["finnhub"], t)
            except ProviderUnavailable:
                pass
    else:
        print("backfill: no FINNHUB_API_KEY -> skipping fundamentals")

    for t in tickers:
        counts["catalysts"] += backfill_catalysts(db, clients, t, start, end, ciks.get(t))

    db.close()
    return counts


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():  # pragma: no cover
    ap = argparse.ArgumentParser(description="Backfill the PIT panel from providers.")
    ap.add_argument("--tickers", required=True, help="comma-separated tickers")
    ap.add_argument("--start", required=True, type=_parse_date)
    ap.add_argument("--end", required=True, type=_parse_date)
    args = ap.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    counts = run(tickers, args.start, args.end)
    print("backfill complete:", counts)


if __name__ == "__main__":  # pragma: no cover
    main()
