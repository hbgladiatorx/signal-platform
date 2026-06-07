"""Idempotent panel writers used by ingest.

Every writer is an upsert keyed on the table's natural PK so a backfill can be
re-run safely. These are the ONLY functions that write panel facts; they do not
compute or filter -- the loaders (loaders.py) own the transform + knowable_at
stamping, and the panel (store/panel.py) owns the as-of read filter.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from ..store.db import Database


def _ins(db: Database, table: str, cols: list[str], conflict: list[str]) -> str:
    placeholders = ", ".join("?" for _ in cols)
    collist = ", ".join(cols)
    if db.flavor == "sqlite":
        return f"INSERT OR REPLACE INTO {table} ({collist}) VALUES ({placeholders})"
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in conflict)
    return (
        f"INSERT INTO {table} ({collist}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(conflict)}) DO UPDATE SET {updates}"
    )


def upsert_prices(db: Database, rows: Iterable[dict[str, Any]]) -> int:
    cols = ["ticker", "date", "open", "high", "low", "close", "volume", "adj_close"]
    sql = _ins(db, "prices", cols, ["ticker", "date"])
    data = [[r.get(c) for c in cols] for r in rows]
    db.executemany(sql, data)
    return len(data)


def upsert_universe(db: Database, rows: Iterable[dict[str, Any]]) -> int:
    cols = ["ticker", "as_of", "active", "delisted_date", "optionable", "market_cap"]
    sql = _ins(db, "universe", cols, ["ticker", "as_of"])
    data = [[r.get(c) for c in cols] for r in rows]
    db.executemany(sql, data)
    return len(data)


def upsert_fundamentals(db: Database, rows: Iterable[dict[str, Any]]) -> int:
    cols = ["ticker", "period_end", "knowable_at", "fcf", "gross_margin",
            "op_margin", "debt_to_equity", "as_reported"]
    sql = _ins(db, "fundamentals", cols, ["ticker", "period_end"])
    data = [[r.get(c) for c in cols] for r in rows]
    db.executemany(sql, data)
    return len(data)


def upsert_catalysts(db: Database, rows: Iterable[dict[str, Any]]) -> int:
    cols = ["catalyst_id", "ticker", "catalyst_type", "source", "knowable_at",
            "event_date", "tier", "requires_review", "payload"]
    sql = _ins(db, "catalysts", cols, ["catalyst_id"])
    data = []
    for r in rows:
        row = dict(r)
        if isinstance(row.get("payload"), (dict, list)):
            row["payload"] = json.dumps(row["payload"])
        data.append([row.get(c) for c in cols])
    db.executemany(sql, data)
    return len(data)


def upsert_iv(db: Database, rows: Iterable[dict[str, Any]]) -> int:
    cols = ["ticker", "date", "atm_iv"]
    sql = _ins(db, "iv_snapshots", cols, ["ticker", "date"])
    data = [[r.get(c) for c in cols] for r in rows]
    db.executemany(sql, data)
    return len(data)
