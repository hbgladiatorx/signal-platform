"""Historical OHLCV backfill for single-leg OPTIONS from Alpaca.

Alpaca provides options market data (your key is entitled — verified). This tool
pulls historical option bars and lands them where backtests read from, exactly
like scripts/backfill_history.py does for equities/crypto:

  backtests read `cagg_bars_*`; source of truth is the 1m cagg's materialized
  hypertable. We insert one real OHLCV row per bar into that hypertable (below
  the live watermark) and refresh the higher caggs so 5m..1d roll up.

Options-specific extras this script handles that the equity one doesn't:
  - CREATE the option instrument row (asset_class='option', with underlying /
    right / strike / expiry / multiplier=100) so load_instrument_meta() can give
    the engine the contract multiplier + expiry settlement.
  - Parse the OCC symbol (SPY260812C00500000 -> SPY, 2026-08-12, C, 500.000).
  - Discover near-the-money contracts for an underlying via Alpaca option
    snapshots, or take an explicit --symbols list.

Alpaca option history starts ~Feb 2024; earlier windows return nothing.

Usage (inside the api container — has asyncpg, DATABASE_URL, ALPACA_DATA_*):
  # explicit contracts
  python scripts/backfill_alpaca_options.py --interval 1Day --start 2025-01-01 \
      --symbols SPY260812C00500000,SPY260812P00500000
  # discover the N nearest-ATM contracts for the nearest expiries of an underlier
  python scripts/backfill_alpaca_options.py --underlying SPY --max-contracts 20 \
      --interval 1Day --start 2025-01-01
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import asyncpg

MAT_1M = "_timescaledb_internal._materialized_hypertable_5"
HIGHER_CAGGS = ["cagg_bars_5m", "cagg_bars_10m", "cagg_bars_15m", "cagg_bars_30m",
                "cagg_bars_1h", "cagg_bars_4h", "cagg_bars_1d"]

DATA_BASE = "https://data.alpaca.markets"
# Alpaca timeframe strings per --interval. A bar lands at its start minute in the
# 1m cagg; 1Day fills 1d correctly (sub-day sparse), 1Min fills every resolution.
TF = {"1Min": "1Min", "1Hour": "1Hour", "1Day": "1Day"}

KEY = os.environ.get("ALPACA_DATA_KEY_ID", "")
SECRET = os.environ.get("ALPACA_DATA_SECRET", "")
FEED = os.environ.get("ALPACA_OPTIONS_FEED", "opra")  # 'opra' (paid) | 'indicative'


def log(msg: str) -> None:
    print(f"[opt-backfill {datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def _get_json(url: str, retries: int = 5) -> dict:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "APCA-API-KEY-ID": KEY,
                "APCA-API-SECRET-KEY": SECRET,
                "User-Agent": "signal-opt-backfill/1.0",
            })
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200] if hasattr(e, "read") else ""
            if e.code in (429, 500, 502, 503, 504):
                wait = min(60, 2 ** attempt * 3)
                log(f"  HTTP {e.code}; backoff {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {body}") from e
        except Exception as e:  # noqa: BLE001
            wait = min(30, 2 ** attempt * 2)
            log(f"  {type(e).__name__}: {str(e)[:120]}; retry {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"GET failed after {retries}: {url[:120]}")


# ---- OCC parsing -----------------------------------------------------------
def parse_occ(occ: str) -> tuple[str, date, str, Decimal]:
    """SPY260812C00500000 -> ('SPY', date(2026,8,12), 'C', Decimal('500.000'))."""
    strike = Decimal(occ[-8:]) / Decimal(1000)
    right = occ[-9]
    yy, mm, dd = int(occ[-15:-13]), int(occ[-13:-11]), int(occ[-11:-9])
    root = occ[:-15]
    return root, date(2000 + yy, mm, dd), right, strike


def _minute_floor(iso_ts: str) -> datetime:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return dt.replace(second=0, microsecond=0, tzinfo=timezone.utc)


# ---- Alpaca fetchers -------------------------------------------------------
def fetch_option_bars(occ: str, interval: str, start: str, end: str):
    """Yield (bucket_dt, o,h,l,c,vol,trade_count,vwap) for one OCC contract."""
    token = None
    while True:
        q = {
            "symbols": occ, "timeframe": TF[interval], "start": start, "end": end,
            "limit": "10000", "sort": "asc", "feed": FEED,
        }
        if token:
            q["page_token"] = token
        d = _get_json(f"{DATA_BASE}/v1beta1/options/bars?{urllib.parse.urlencode(q)}")
        for b in (d.get("bars") or {}).get(occ, []) or []:
            yield (
                _minute_floor(b["t"]),
                b["o"], b["h"], b["l"], b["c"],
                b.get("v", 0) or 0, int(b.get("n", 0) or 0), b.get("vw"),
            )
        token = d.get("next_page_token")
        if not token:
            break
        time.sleep(0.2)


def discover_contracts(underlying: str, max_contracts: int) -> list[str]:
    """Return up to max_contracts OCC symbols for `underlying`, nearest-the-money
    across the soonest expiries, via option snapshots."""
    # Underlying spot from its stock latest trade (best-effort; falls back to
    # median strike if unavailable).
    spot = None
    try:
        t = _get_json(f"{DATA_BASE}/v2/stocks/{underlying}/trades/latest")
        spot = float(t.get("trade", {}).get("p") or 0) or None
    except Exception:  # noqa: BLE001
        pass
    occs: list[str] = []
    token = None
    while True:
        q = {"limit": "1000", "feed": FEED}
        if token:
            q["page_token"] = token
        d = _get_json(
            f"{DATA_BASE}/v1beta1/options/snapshots/{underlying}?{urllib.parse.urlencode(q)}"
        )
        occs.extend((d.get("snapshots") or {}).keys())
        token = d.get("next_page_token")
        if not token:
            break
        time.sleep(0.2)
    if not occs:
        return []
    parsed = [(o, *parse_occ(o)) for o in occs]  # (occ, root, expiry, right, strike)
    if spot is None:
        strikes = sorted(float(p[4]) for p in parsed)
        spot = strikes[len(strikes) // 2]
    # Nearest expiries first, then nearest-the-money within them.
    parsed.sort(key=lambda p: (p[2], abs(float(p[4]) - spot)))
    return [p[0] for p in parsed[:max_contracts]]


# ---- DB --------------------------------------------------------------------
async def upsert_instrument(conn, occ: str, underlying: str) -> int:
    root, expiry, right, strike = parse_occ(occ)
    canonical = f"{occ}@ALPACA"
    return await conn.fetchval(
        """
        INSERT INTO instruments (asset_class, canonical_symbol, venue, native_symbol,
            base, quote, underlying, option_right, strike, expiry, multiplier, active)
        VALUES ('option', $1, 'ALPACA', $2, $3, 'USD', $4, $5, $6, $7, 100, true)
        ON CONFLICT (canonical_symbol) DO UPDATE SET
            underlying = EXCLUDED.underlying, option_right = EXCLUDED.option_right,
            strike = EXCLUDED.strike, expiry = EXCLUDED.expiry,
            multiplier = EXCLUDED.multiplier, active = true
        RETURNING id
        """,
        canonical, occ, root, f"{underlying}@ALPACA", right, strike, expiry,
    )


async def existing_buckets(conn, iid: int, lo: datetime, hi: datetime) -> set:
    rows = await conn.fetch(
        f"select bucket from {MAT_1M} where instrument_id=$1 and bucket>=$2 and bucket<$3",
        iid, lo, hi,
    )
    return {r["bucket"] for r in rows}


async def backfill_contract(conn, occ, underlying, interval, start_dt, end_dt, watermark):
    iid = await upsert_instrument(conn, occ, underlying)
    have = await existing_buckets(conn, iid, start_dt, end_dt)
    rows = []
    for bucket, o, h, l, c, vol, n, vw in fetch_option_bars(
        occ, interval, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
    ):
        if bucket >= watermark or bucket < start_dt or bucket >= end_dt or bucket in have:
            continue
        have.add(bucket)
        vol = float(vol or 0)
        pv = (float(vw) * vol) if vw is not None else (float(c) * vol)
        rows.append((iid, bucket, float(o), float(h), float(l), float(c),
                     vol, int(n or 0), pv, vol))
    if not rows:
        return 0, None, None
    rows.sort(key=lambda r: r[1])
    await conn.copy_records_to_table(
        "_materialized_hypertable_5", schema_name="_timescaledb_internal",
        columns=["instrument_id", "bucket", "open", "high", "low", "close",
                 "volume", "trade_count", "price_volume_sum", "volume_for_vwap"],
        records=rows,
    )
    return len(rows), rows[0][1], rows[-1][1]


async def refresh_caggs(conn, lo: datetime, hi: datetime):
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
    ap.add_argument("--symbols", default=None, help="comma-separated OCC (with or without @ALPACA)")
    ap.add_argument("--underlying", default=None, help="e.g. SPY — discover contracts")
    ap.add_argument("--max-contracts", type=int, default=20)
    ap.add_argument("--interval", choices=["1Min", "1Hour", "1Day"], default="1Day")
    ap.add_argument("--start", default="2024-02-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--no-refresh", action="store_true")
    args = ap.parse_args()

    if not KEY or not SECRET:
        raise SystemExit("ALPACA_DATA_KEY_ID / ALPACA_DATA_SECRET not set.")
    start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = (datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
              if args.end else datetime.now(timezone.utc))

    if args.symbols:
        occs = [s.strip().split("@", 1)[0] for s in args.symbols.split(",") if s.strip()]
        underlying = args.underlying or parse_occ(occs[0])[0]
    elif args.underlying:
        log(f"discovering up to {args.max_contracts} nearest-ATM {args.underlying} contracts…")
        occs = discover_contracts(args.underlying, args.max_contracts)
        underlying = args.underlying
        log(f"  found {len(occs)}: {', '.join(occs[:6])}{'…' if len(occs) > 6 else ''}")
    else:
        raise SystemExit("Provide --symbols or --underlying.")
    if not occs:
        raise SystemExit("No contracts to backfill.")

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        watermark = await conn.fetchval(
            "select _timescaledb_functions.to_timestamp(_timescaledb_functions.cagg_watermark(5))"
        )
        total = 0
        g_lo = g_hi = None
        for i, occ in enumerate(occs, 1):
            try:
                n, lo, hi = await backfill_contract(
                    conn, occ, underlying, args.interval, start_dt, end_dt, watermark
                )
                total += n
                if n:
                    g_lo = lo if g_lo is None else min(g_lo, lo)
                    g_hi = hi if g_hi is None else max(g_hi, hi)
                    log(f"[{i}/{len(occs)}] {occ}: +{n} bars {lo.date()}..{hi.date()} (total {total})")
                else:
                    log(f"[{i}/{len(occs)}] {occ}: nothing new")
            except Exception as e:  # noqa: BLE001
                log(f"[{i}/{len(occs)}] {occ}: ERROR {type(e).__name__}: {str(e)[:160]}")
        if g_lo and g_hi and not args.no_refresh:
            log(f"refreshing caggs over {g_lo.date()}..{g_hi.date()} …")
            await refresh_caggs(conn, g_lo, g_hi)
        log(f"DONE: {total} option bars inserted across {len(occs)} contract(s)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
