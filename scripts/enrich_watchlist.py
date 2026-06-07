#!/usr/bin/env python3
"""STAGE C -- enrich ONLY the watchlist with per-ticker data.

For each watchlist ticker: market cap + optionability (Polygon), fundamentals
(Finnhub), and EDGAR 8-K / 13D / 13G catalysts. Prices are already in the panel
from Stage A, so we skip them here. This is the only place per-ticker API budget
is spent -- on a few hundred names, not ten thousand.

    python scripts/enrich_watchlist.py [--watchlist watchlist.txt] [--end 2026-05-14]
"""
from __future__ import annotations

import argparse, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))

from catalyst import config as cfgmod
from catalyst.store.db import Database
from catalyst.ingest import backfill


def _d(s): return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watchlist", default=str(ROOT / "watchlist.txt"))
    ap.add_argument("--start", default="2023-08-01", type=_d)
    ap.add_argument("--end", default="2026-05-14", type=_d)
    args = ap.parse_args()

    tickers = [t.strip().upper() for t in Path(args.watchlist).read_text().split() if t.strip()]
    cfg = cfgmod.load()
    db = Database(cfg.runtime.database_url); db.bootstrap()
    clients = backfill.build_clients(cfg)

    # Resolve CIKs once for EDGAR catalysts.
    ciks = {}
    try:
        full = clients["edgar"].ticker_cik_map()
        ciks = {t: full[t] for t in tickers if t in full}
    except Exception as e:
        print(f"CIK resolution failed: {type(e).__name__}")

    counts = {"universe": 0, "fundamentals": 0, "catalysts": 0}
    if "polygon" in clients:
        counts["universe"] += backfill.backfill_universe(db, clients["polygon"], tickers, args.end)
    for i, t in enumerate(tickers, 1):
        if "finnhub" in clients:
            try:
                counts["fundamentals"] += backfill.backfill_fundamentals(db, clients["finnhub"], t)
            except Exception:
                pass
        counts["catalysts"] += backfill.backfill_catalysts(db, clients, t, args.start, args.end, ciks.get(t))
        if i % 25 == 0:
            print(f"  enriched {i}/{len(tickers)}  {counts}", flush=True)

    print(f"STAGE C complete: {counts}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
