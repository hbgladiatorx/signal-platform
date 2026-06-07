#!/usr/bin/env python3
"""STAGE A -- full-universe daily prices via Polygon grouped-daily (1 call/day).

Survivorship-correct (delisted names appear on days they traded). Disk-cached and
resumable: re-running skips days already fetched.

    python scripts/ingest_universe_prices.py --start 2023-08-01 --end 2026-05-14
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
    ap.add_argument("--start", required=True, type=_d)
    ap.add_argument("--end", required=True, type=_d)
    args = ap.parse_args()
    cfg = cfgmod.load()
    db = Database(cfg.runtime.database_url); db.bootstrap()
    clients = backfill.build_clients(cfg)
    if "polygon" not in clients:
        print("No POLYGON_API_KEY -> cannot fetch prices."); return 1
    res = backfill.backfill_universe_prices(db, clients["polygon"], args.start, args.end)
    n_tickers = db.execute("SELECT COUNT(DISTINCT ticker) n FROM prices", ())[0]["n"]
    print(f"STAGE A complete: {res}  distinct_tickers_in_panel={n_tickers}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
