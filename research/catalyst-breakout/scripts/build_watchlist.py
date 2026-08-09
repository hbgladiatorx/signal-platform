#!/usr/bin/env python3
"""STAGE B -- price-only distress+liquidity scan over the full price panel.

Cuts the ~10k-name universe down to the distressed-and-liquid watchlist (Module 1
intent: 150-400 names). Writes the tickers to watchlist.txt for Stage C enrich.
No API calls -- pure compute over the prices Stage A already pulled.

    python scripts/build_watchlist.py [--limit 400]
"""
from __future__ import annotations

import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))

from catalyst import config as cfgmod
from catalyst.store.db import Database
from catalyst.screen.universe_scan import scan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400, help="cap watchlist size (most-distressed first)")
    ap.add_argument("--out", default=str(ROOT / "watchlist.txt"))
    args = ap.parse_args()
    cfg = cfgmod.load()
    db = Database(cfg.runtime.database_url)
    entries = scan(db, cfg)
    db.close()

    kept = entries[:args.limit]
    Path(args.out).write_text("\n".join(e.ticker for e in kept) + "\n")
    print(f"scanned universe -> {len(entries)} distressed+liquid names; keeping {len(kept)} (limit={args.limit})")
    print(f"written to {args.out}\n")
    print(f"{'ticker':8}{'maxDD':>8}{'firstQualified':>16}{'avgDollarVol':>16}")
    for e in kept[:30]:
        print(f"{e.ticker:8}{e.max_drawdown*100:7.0f}%{e.first_qualified:>16}{e.avg_dollar_vol/1e6:>13.0f}M")
    if len(kept) > 30:
        print(f"  ... and {len(kept)-30} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
