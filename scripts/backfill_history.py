"""Historical OHLCV backfill for 2025/26 across the platform.

The platform has NO historical-fetch path — both adapters are streaming-only
websockets, so older history was seeded out-of-band. This tool fills the gap.

Sources (verified to serve the target window):
  - Equities: Polygon aggregates REST  (/v2/aggs/.../range/1/minute|hour|day)
  - Crypto:   Binance.US klines REST    (/api/v3/klines)  — keyless/public

Storage model (important): backtests read the TimescaleDB continuous aggregates
`cagg_bars_*`, whose source of truth is `trades` → `cagg_bars_1m` → higher
caggs. Fabricating trades to reconstruct OHLC would be 4+ rows/bar and hundreds
of millions of rows. Instead we insert the REAL OHLCV one row per bar directly
into the 1m cagg's materialized hypertable (below the live watermark, so live
ingestion never touches it), then refresh the higher caggs over the range so
5m/15m/1h/4h/1d roll up correctly. Each fetched bar is placed at its start
minute: fetch 1m → all resolutions dense/correct; fetch 1h → 1h+1d correct
(sub-hour sparse); fetch 1d → 1d correct.

Resumable: existing (instrument_id, bucket) pairs in the target window are
loaded and skipped, so re-running only fills holes.

Usage (inside the api container, which has asyncpg + DATABASE_URL):
  python scripts/backfill_history.py --asset crypto --interval 1h --start 2025-01-01
  python scripts/backfill_history.py --asset equity --interval 1m --start 2025-01-01
  python scripts/backfill_history.py --asset crypto --interval 1m --symbols BTC-USDT@BINANCEUS,ETH-USDT@BINANCEUS
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import asyncpg

# 1m continuous-aggregate materialized hypertable + the dependent caggs to
# refresh (in dependency order). _materialized_hypertable_5 == cagg_bars_1m.
MAT_1M = "_timescaledb_internal._materialized_hypertable_5"
HIGHER_CAGGS = ["cagg_bars_5m", "cagg_bars_15m", "cagg_bars_1h", "cagg_bars_4h", "cagg_bars_1d"]

# Polygon aggregate timespan per interval.
POLY_SPAN = {"1m": ("1", "minute"), "1h": ("1", "hour"), "1d": ("1", "day")}
# Binance.US kline interval strings.
BINANCE_INTERVAL = {"1m": "1m", "1h": "1h", "1d": "1d"}

POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "")


def log(msg: str) -> None:
    print(f"[backfill {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def _http_get_json(url: str, retries: int = 5) -> dict | list:
    """GET JSON with basic 429/5xx backoff."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "signal-backfill/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                wait = min(60, 2 ** attempt * 3)
                log(f"  HTTP {e.code}; backoff {wait}s")
                time.sleep(wait)
                continue
            raise
        except Exception as e:  # noqa: BLE001 — network flakiness; retry
            wait = min(30, 2 ** attempt * 2)
            log(f"  {type(e).__name__}: {str(e)[:120]}; retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"GET failed after {retries} retries: {url[:120]}")


def _minute_floor_ms(ms: int) -> datetime:
    return datetime.fromtimestamp((ms // 60000) * 60, tz=timezone.utc)


# ---------------- Source fetchers: yield (bucket_dt, o,h,l,c,vol,trade_count,vwap) ----------------
def fetch_polygon(ticker: str, interval: str, start: str, end: str):
    mult, span = POLY_SPAN[interval]
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{urllib.parse.quote(ticker)}/range/{mult}/{span}/"
        f"{start}/{end}?adjusted=true&sort=asc&limit=50000&apiKey={POLYGON_KEY}"
    )
    while url:
        d = _http_get_json(url)
        for b in (d.get("results") or []):
            yield (
                _minute_floor_ms(int(b["t"])),
                b["o"], b["h"], b["l"], b["c"],
                b.get("v", 0) or 0, int(b.get("n", 0) or 0), b.get("vw"),
            )
        nxt = d.get("next_url")
        url = f"{nxt}&apiKey={POLYGON_KEY}" if nxt else None
        if url:
            time.sleep(0.2)


def fetch_binance(symbol: str, interval: str, start_ms: int, end_ms: int):
    iv = BINANCE_INTERVAL[interval]
    cur = start_ms
    while cur < end_ms:
        url = (
            f"https://api.binance.us/api/v3/klines?symbol={symbol}&interval={iv}"
            f"&startTime={cur}&endTime={end_ms}&limit=1000"
        )
        rows = _http_get_json(url)
        if not isinstance(rows, list) or not rows:
            break
        for k in rows:
            yield (
                _minute_floor_ms(int(k[0])),
                float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                float(k[5]), int(k[8]), None,
            )
        last_open = int(rows[-1][0])
        nxt = last_open + 1
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.06)  # ~well under Binance.US rate limit


def to_binance_symbol(canonical: str) -> str:
    # "BTC-USDT@BINANCEUS" -> "BTCUSDT"
    base = canonical.split("@", 1)[0]
    return base.replace("-", "")


def to_polygon_ticker(canonical: str) -> str:
    # "SPY@ALPACA" -> "SPY"
    return canonical.split("@", 1)[0]


async def get_instruments(conn, asset: str, symbols: list[str] | None):
    if symbols:
        rows = await conn.fetch(
            "select id, canonical_symbol from instruments where canonical_symbol = any($1)",
            symbols,
        )
    elif asset == "equity":
        rows = await conn.fetch(
            "select id, canonical_symbol from instruments where asset_class='equity' order by canonical_symbol"
        )
    else:
        rows = await conn.fetch(
            "select id, canonical_symbol from instruments where asset_class='crypto_spot' order by canonical_symbol"
        )
    return [(r["id"], r["canonical_symbol"]) for r in rows]


async def existing_buckets(conn, instrument_id: int, start_dt: datetime, end_dt: datetime) -> set:
    rows = await conn.fetch(
        f"select bucket from {MAT_1M} where instrument_id=$1 and bucket >= $2 and bucket < $3",
        instrument_id, start_dt, end_dt,
    )
    return {r["bucket"] for r in rows}


async def backfill_symbol(conn, instrument_id, canonical, asset, interval, start_dt, end_dt, watermark):
    have = await existing_buckets(conn, instrument_id, start_dt, end_dt)
    start_s = start_dt.strftime("%Y-%m-%d")
    end_s = end_dt.strftime("%Y-%m-%d")

    if asset == "equity":
        gen = fetch_polygon(to_polygon_ticker(canonical), interval, start_s, end_s)
    else:
        gen = fetch_binance(
            to_binance_symbol(canonical),
            interval,
            int(start_dt.timestamp() * 1000),
            int(end_dt.timestamp() * 1000),
        )

    rows = []
    for bucket, o, h, l, c, vol, n, vw in gen:
        # Never collide with live data (>= watermark) or stray outside window.
        if bucket >= watermark or bucket < start_dt or bucket >= end_dt:
            continue
        if bucket in have:
            continue
        have.add(bucket)
        vol = float(vol or 0)
        pv = (float(vw) * vol) if vw is not None else (float(c) * vol)
        rows.append((instrument_id, bucket, float(o), float(h), float(l), float(c),
                     vol, int(n or 0), pv, vol))

    if not rows:
        return 0, None, None
    rows.sort(key=lambda r: r[1])
    await conn.copy_records_to_table(
        "_materialized_hypertable_5",
        schema_name="_timescaledb_internal",
        columns=["instrument_id", "bucket", "open", "high", "low", "close",
                 "volume", "trade_count", "price_volume_sum", "volume_for_vwap"],
        records=rows,
    )
    return len(rows), rows[0][1], rows[-1][1]


async def refresh_caggs(conn, lo: datetime, hi: datetime):
    # refresh_continuous_aggregate cannot run inside a txn; asyncpg autocommits
    # simple execute() calls. Pad the window by a day on each side.
    from datetime import timedelta
    # refresh_continuous_aggregate has typed args that asyncpg can't infer via
    # $-params, so inline the (self-controlled) timestamps as casted literals.
    a = (lo - timedelta(days=1)).isoformat()
    b = (hi + timedelta(days=2)).isoformat()
    for cagg in HIGHER_CAGGS:
        try:
            await conn.execute(
                f"CALL refresh_continuous_aggregate('{cagg}', "
                f"'{a}'::timestamptz, '{b}'::timestamptz)"
            )
        except Exception as e:  # noqa: BLE001
            log(f"  refresh {cagg} warn: {str(e)[:100]}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", choices=["equity", "crypto"], required=True)
    ap.add_argument("--interval", choices=["1m", "1h", "1d"], default="1h")
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default=None, help="default = now")
    ap.add_argument("--symbols", default=None, help="comma-separated canonical symbols")
    ap.add_argument("--limit-symbols", type=int, default=None)
    ap.add_argument("--no-refresh", action="store_true",
                    help="insert raw bars only; skip the continuous-aggregate refresh")
    args = ap.parse_args()

    start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = (
        datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.end else datetime.now(timezone.utc)
    )
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        watermark = await conn.fetchval(
            "select _timescaledb_functions.to_timestamp(_timescaledb_functions.cagg_watermark(5))"
        )
        instruments = await get_instruments(conn, args.asset, symbols)
        if args.limit_symbols:
            instruments = instruments[: args.limit_symbols]
        log(f"asset={args.asset} interval={args.interval} symbols={len(instruments)} "
            f"window={start_dt.date()}..{end_dt.date()} watermark={watermark}")

        total = 0
        g_lo: datetime | None = None
        g_hi: datetime | None = None
        for i, (iid, canonical) in enumerate(instruments, 1):
            try:
                n, lo, hi = await backfill_symbol(
                    conn, iid, canonical, args.asset, args.interval, start_dt, end_dt, watermark
                )
                total += n
                if n and lo and hi:
                    g_lo = lo if g_lo is None else min(g_lo, lo)
                    g_hi = hi if g_hi is None else max(g_hi, hi)
                    log(f"[{i}/{len(instruments)}] {canonical}: +{n} bars {lo.date()}..{hi.date()} (total {total})")
                else:
                    log(f"[{i}/{len(instruments)}] {canonical}: nothing new")
            except Exception as e:  # noqa: BLE001 — keep going on per-symbol failure
                log(f"[{i}/{len(instruments)}] {canonical}: ERROR {type(e).__name__}: {str(e)[:160]}")
        # ONE cagg refresh pass over the whole inserted range — far cheaper than
        # refreshing 5 caggs per symbol over the full window.
        if g_lo and g_hi and not args.no_refresh:
            log(f"refreshing caggs once over {g_lo.date()}..{g_hi.date()} ...")
            await refresh_caggs(conn, g_lo, g_hi)
        log(f"DONE asset={args.asset} interval={args.interval}: {total} bars inserted")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
