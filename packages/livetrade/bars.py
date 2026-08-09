"""Load OHLCV bars from the continuous-aggregate tables.

Extracted from services/backtest_worker so both the backtest worker and the
live paper-trading runner load history the same way. The runner uses this to
warm-start a strategy's in-memory history before advancing it with live
bars:closed events.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# Maps a bar_resolution to its continuous-aggregate table.
RESOLUTION_TABLE: dict[str, str] = {
    "1m": "cagg_bars_1m",
    "5m": "cagg_bars_5m",
    "10m": "cagg_bars_10m",
    "15m": "cagg_bars_15m",
    "30m": "cagg_bars_30m",
    "1h": "cagg_bars_1h",
    "4h": "cagg_bars_4h",
    "1d": "cagg_bars_1d",
}

_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


async def load_bars(
    engine: AsyncEngine,
    symbol: str,
    resolution: str,
    *,
    limit: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Load OHLCV bars for `symbol` at `resolution`, indexed by bucket (UTC).

    If `limit` is given, returns only the most recent `limit` bars (still in
    ascending chronological order) — used by the live runner to bound
    warm-start history. With `limit=None` returns the full history (backtest).

    `start`/`end` bound the query by bucket (inclusive) in SQL, so a windowed
    backtest only loads the requested date range instead of the symbol's entire
    history. Both default to None (no bound). They compose with `limit`: the
    newest `limit` bars *within* the window are returned.
    """
    table = RESOLUTION_TABLE.get(resolution)
    if table is None:
        raise ValueError(
            f"Unknown bar_resolution: {resolution!r}. "
            f"Valid: {list(RESOLUTION_TABLE.keys())}"
        )

    # Optional date-window predicate, pushed into SQL so we never materialize
    # bars outside the requested range.
    window_sql = ""
    params: dict = {"symbol": symbol}
    if start is not None:
        window_sql += " AND b.bucket >= :start"
        params["start"] = start
    if end is not None:
        window_sql += " AND b.bucket <= :end"
        params["end"] = end

    # When limiting, take the newest N by ordering DESC then re-sort ascending
    # in pandas. Without a limit, let the DB return ascending directly.
    if limit is not None:
        query = text(
            f"""
            SELECT b.bucket, b.open, b.high, b.low, b.close, b.volume
            FROM {table} b
            JOIN instruments i ON i.id = b.instrument_id
            WHERE i.canonical_symbol = :symbol{window_sql}
            ORDER BY b.bucket DESC
            LIMIT :limit
            """
        )
        params["limit"] = limit
    else:
        query = text(
            f"""
            SELECT b.bucket, b.open, b.high, b.low, b.close, b.volume
            FROM {table} b
            JOIN instruments i ON i.id = b.instrument_id
            WHERE i.canonical_symbol = :symbol{window_sql}
            ORDER BY b.bucket
            """
        )

    async with engine.connect() as conn:
        result = await conn.execute(query, params)
        rows = result.mappings().all()

    if not rows:
        return pd.DataFrame(columns=list(_OHLCV_COLUMNS))

    df = pd.DataFrame(rows)
    df["bucket"] = pd.to_datetime(df["bucket"], utc=True)
    df = df.set_index("bucket")
    for col in _OHLCV_COLUMNS:
        df[col] = df[col].astype(float)
    df = df.sort_index()  # ascending; corrects the DESC fetch when limited
    return df
