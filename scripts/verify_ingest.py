#!/usr/bin/env python3
"""Stdlib-only verification of the ingest layer (no keys, no network).

Feeds canned provider payloads through the loaders + upsert, then reads them back
through the PIT panel to confirm knowable_at stamping holds the as-of line.

    python scripts/verify_ingest.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from catalyst.store.db import Database
from catalyst.store.panel import AsOfPanel
from catalyst.ingest import loaders, upsert

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if cond:
        PASS += 1
    else:
        FAIL += 1


def epoch_ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


def fresh_db():
    db = Database("sqlite:///:memory:")
    db.bootstrap()
    return db


def t_prices():
    print("\n# prices_from_polygon")
    db = fresh_db()
    aggs = [{"t": epoch_ms(2023, 3, 15), "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 1_000_000}]
    rows = loaders.prices_from_polygon("ACME", aggs)
    check("epoch ms -> correct date", rows[0]["date"] == "2023-03-15")
    check("adj_close populated from close", rows[0]["adj_close"] == 10.5)
    n = upsert.upsert_prices(db, rows)
    check("upsert wrote 1 row", n == 1)
    db.close()


def t_fundamentals_pit():
    print("\n# fundamentals_from_finnhub (knowable_at = filing acceptance)")
    db = fresh_db()
    payload = {"data": [{
        "endDate": "2023-03-31", "acceptedDate": "2023-05-04",
        "report": {
            "ic": [{"concept": "Revenues", "value": 1000},
                   {"concept": "OperatingIncomeLoss", "value": 100},
                   {"concept": "GrossProfit", "value": 400}],
            "cf": [{"concept": "NetCashProvidedByUsedInOperatingActivities", "value": 200},
                   {"concept": "PaymentsToAcquirePropertyPlantAndEquipment", "value": 50}],
            "bs": [{"concept": "LongTermDebt", "value": 300},
                   {"concept": "StockholdersEquity", "value": 600}],
        },
    }]}
    rows = loaders.fundamentals_from_finnhub("ACME", payload)
    r = rows[0]
    check("knowable_at = acceptedDate", r["knowable_at"] == "2023-05-04")
    check("period_end = endDate", r["period_end"] == "2023-03-31")
    check("fcf = opcf - capex", r["fcf"] == 150)
    check("op_margin = opinc/rev", abs(r["op_margin"] - 0.1) < 1e-9)
    check("debt_to_equity", abs(r["debt_to_equity"] - 0.5) < 1e-9)
    upsert.upsert_fundamentals(db, rows)

    # PIT: invisible before filing, visible after.
    before = AsOfPanel(db, date(2023, 4, 15)).fundamentals("ACME")
    after = AsOfPanel(db, date(2023, 5, 10)).fundamentals("ACME")
    check("hidden before acceptedDate", not any(f["period_end"] == "2023-03-31" for f in before))
    check("visible after acceptedDate", any(f["period_end"] == "2023-03-31" for f in after))
    db.close()


def t_catalysts():
    print("\n# catalyst loaders (knowable_at stamping)")
    db = fresh_db()
    earn = loaders.catalysts_from_earnings("ACME", [
        {"period": "2023-07-25", "estimate": 1.0, "actual": 1.2, "guidance_raise": True}])
    check("earnings surprise pct", abs(earn[0]["payload"]["surprise_pct"] - 20.0) < 1e-9)
    check("earnings knowable_at", earn[0]["knowable_at"] == "2023-07-25")

    edgar = loaders.catalysts_from_edgar("ACME", [
        {"form": "SC 13D", "acceptanceDateTime": "2023-09-18T16:30:11.000Z",
         "filingDate": "2023-09-18", "accessionNumber": "0001"}])
    check("13D -> validator tier", edgar[0]["tier"] == "validator")
    check("13D requires_review", edgar[0]["requires_review"] == 1)
    check("13D knowable_at = acceptance date", edgar[0]["knowable_at"] == "2023-09-18")

    fed = loaders.catalysts_from_federal("ACME", [
        {"Award ID": "W911", "Award Amount": 250_000_000, "Start Date": "2024-02-01"}])
    check("federal knowable_at = award start", fed[0]["knowable_at"] == "2024-02-01")

    upsert.upsert_catalysts(db, earn + edgar + fed)
    # PIT: a catalyst is invisible before its knowable_at.
    seen = {c["knowable_at"] for c in AsOfPanel(db, date(2023, 8, 1)).catalysts("ACME")}
    check("future 13D/federal hidden as of 2023-08-01",
          "2023-07-25" in seen and "2023-09-18" not in seen and "2024-02-01" not in seen)
    db.close()


def t_universe_survivorship():
    print("\n# universe_from_polygon (survivorship)")
    db = fresh_db()
    details = [
        {"ticker": "LIVE", "market_cap": 5e9},
        {"ticker": "GONE", "market_cap": 8e8, "delisted_utc": "2021-06-30T00:00:00Z"},
    ]
    rows = loaders.universe_from_polygon(date(2020, 1, 2), details, optionable={"LIVE", "GONE"})
    upsert.upsert_universe(db, rows)
    u = {r["ticker"]: r for r in AsOfPanel(db, date(2020, 6, 1)).universe()}
    check("later-delisted name retained", "GONE" in u)
    check("delisted_date stamped", u["GONE"]["delisted_date"] == "2021-06-30")
    db.close()


def main():
    print("=" * 70)
    print("INGEST VERIFICATION (stdlib only, no keys)")
    print("=" * 70)
    for fn in (t_prices, t_fundamentals_pit, t_catalysts, t_universe_survivorship):
        fn()
    print("\n" + "=" * 70)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
