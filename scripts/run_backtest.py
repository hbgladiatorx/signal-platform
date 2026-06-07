#!/usr/bin/env python3
"""Run the point-in-time backtest over whatever is in the panel, print the report.

Run AFTER a backfill (python -m catalyst.ingest.backfill ...). This is an
EVENT-STUDY sweep: each ticker is evaluated only on the dates a catalyst became
knowable (mapped to the nearest prior trading day), which matches the strategy
("front-run the validator") and avoids a pointless full cartesian sweep.

Underlying-edge first (Section 9): no chain_fetcher is passed, so the options
overlay is off. Wire one in once the underlying edge is established.

    python scripts/run_backtest.py [--min-n 20] [--db sqlite:///catalyst.db]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from catalyst.store.db import Database
from catalyst.backtest.engine import run_signal
from catalyst.backtest import report
from catalyst import config as config_mod


def candidate_dates(db: Database) -> dict[str, list[str]]:
    """For each ticker, the trading days on which a catalyst was knowable.

    Maps each catalyst knowable_at to the latest price bar <= that date, so the
    signal is evaluated on a real trading day (entry then resolves to T+1 open).
    """
    cats = db.execute("SELECT DISTINCT ticker, substr(knowable_at,1,10) AS k "
                      "FROM catalysts ORDER BY ticker, k", ())
    out: dict[str, list[str]] = {}
    for c in cats:
        bar = db.execute(
            "SELECT MAX(date) AS d FROM prices WHERE ticker = ? AND date <= ?",
            (c["ticker"], c["k"]),
        )
        d = bar[0]["d"] if bar else None
        if d:
            out.setdefault(c["ticker"], [])
            if d not in out[c["ticker"]]:
                out[c["ticker"]].append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="override DATABASE_URL")
    ap.add_argument("--min-n", type=int, default=None, help="override min_trades_per_bucket")
    args = ap.parse_args()

    cfg = config_mod.load()
    if args.min_n is not None:
        cfg = replace(cfg, backtest=replace(cfg.backtest, min_trades_per_bucket=args.min_n))
    db = Database(args.db or cfg.runtime.database_url)
    db.bootstrap()

    cands = candidate_dates(db)
    if not cands:
        print("No catalysts in the panel. Run a backfill first:")
        print("  python -m catalyst.ingest.backfill --tickers ... --start ... --end ...")
        return 1

    n_eval = sum(len(v) for v in cands.values())
    print(f"Evaluating {n_eval} (ticker, catalyst-date) pairs across {len(cands)} names...")
    trades = []
    for ticker, dates in cands.items():
        for as_of in dates:
            t = run_signal(db, ticker, as_of, cfg=cfg)   # chain_fetcher omitted: underlying edge first
            if t is not None:
                trades.append(t)

    print(f"Fired {len(trades)} signals.\n")
    print(report.render_text(report.generate(trades, cfg)))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
