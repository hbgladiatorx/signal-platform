#!/usr/bin/env python3
"""Phase-0 fetcher: OKX public funding-rate history + open-interest + swap/spot
candles for the majors, 2024-01-01 .. now. Writes one parquet/csv per stream to
app/logs/perp/. No auth, no prod DB writes. OKX is the only US-reachable perp
venue (Binance Futures + Bybit are geo-blocked from this box).

Signal use is venue-agnostic: we trade Binance.US USD spot long/flat; OKX
funding/OI/basis are predictors only.
"""
import time, json, sys, os
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

OUT = "/home/signal/app/logs/perp"
os.makedirs(OUT, exist_ok=True)

BASE = "https://www.okx.com"
# Binance.US-tradable majors that also have OKX USDT swaps. base -> okx swap inst
SYMBOLS = {
    "BTC": "BTC-USDT-SWAP", "ETH": "ETH-USDT-SWAP", "BNB": "BNB-USDT-SWAP",
    "SOL": "SOL-USDT-SWAP", "XRP": "XRP-USDT-SWAP", "ADA": "ADA-USDT-SWAP",
    "DOGE": "DOGE-USDT-SWAP", "LINK": "LINK-USDT-SWAP", "AVAX": "AVAX-USDT-SWAP",
    "LTC": "LTC-USDT-SWAP",
}
START_MS = 1704067200000  # 2024-01-01T00:00:00Z


def get(path, params, tries=5):
    q = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    url = f"{BASE}{path}?{q}"
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": "phase0/1.0"})
            with urlopen(req, timeout=20) as r:
                d = json.loads(r.read())
            if d.get("code") not in ("0", 0):
                raise RuntimeError(d.get("msg", d))
            return d["data"]
        except (URLError, HTTPError, RuntimeError) as e:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    return []


def fetch_funding(inst):
    """funding-rate-history: 100/page, page backwards via `after`=oldest ts seen."""
    rows, after = [], None
    while True:
        data = get("/api/v5/public/funding-rate-history",
                   {"instId": inst, "limit": 100, "after": after})
        if not data:
            break
        rows.extend(data)
        oldest = min(int(x["fundingTime"]) for x in data)
        if oldest <= START_MS or len(data) < 100:
            break
        after = oldest
        time.sleep(0.12)
    out = [(int(x["fundingTime"]), float(x["fundingRate"]),
            float(x.get("realizedRate") or x["fundingRate"]))
           for x in rows if int(x["fundingTime"]) >= START_MS]
    out.sort()
    return out  # (ts_ms, fundingRate, realizedRate)


def fetch_candles(inst, bar="1H"):
    """history-candles: 100/page, page backwards via `after`=oldest ts seen."""
    rows, after = [], None
    while True:
        data = get("/api/v5/market/history-candles",
                   {"instId": inst, "bar": bar, "limit": 100, "after": after})
        if not data:
            break
        rows.extend(data)
        oldest = min(int(x[0]) for x in data)
        if oldest <= START_MS or len(data) < 100:
            break
        after = oldest
        time.sleep(0.12)
    out = [(int(x[0]), float(x[4])) for x in rows if int(x[0]) >= START_MS]  # ts, close
    out.sort()
    return out


def fetch_oi_hist(ccy):
    """rubik OI-volume history (1H). Limited lookback on OKX; best-effort."""
    try:
        data = get("/api/v5/rubik/stat/contracts/open-interest-volume",
                   {"ccy": ccy, "period": "1H"})
    except Exception as e:
        print(f"  OI {ccy}: {e}", file=sys.stderr)
        return []
    out = [(int(x[0]), float(x[1])) for x in data if int(x[0]) >= START_MS]  # ts, oi_usd
    out.sort()
    return out


def write_csv(path, header, rows):
    with open(path, "w") as f:
        f.write(",".join(header) + "\n")
        for r in rows:
            f.write(",".join(str(v) for v in r) + "\n")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    with_candles = "--candles" in flags          # basis stream, slow; off by default
    only = args or None
    summary = {}
    for base, inst in SYMBOLS.items():
        if only and base not in only:
            continue
        t0 = time.time()
        fund = fetch_funding(inst)
        write_csv(f"{OUT}/{base}_funding.csv", ["ts_ms", "funding", "realized"], fund)
        oi = fetch_oi_hist(base)
        write_csv(f"{OUT}/{base}_oi_1h.csv", ["ts_ms", "oi_usd"], oi)
        sw = sp = 0
        if with_candles:
            swap = fetch_candles(inst, "1H")
            spot = fetch_candles(f"{base}-USDT", "1H")
            write_csv(f"{OUT}/{base}_swap_1h.csv", ["ts_ms", "close"], swap)
            write_csv(f"{OUT}/{base}_spot_1h.csv", ["ts_ms", "close"], spot)
            sw, sp = len(swap), len(spot)
        summary[base] = {"funding_n": len(fund),
                         "funding_from": fund[0][0] if fund else None,
                         "swap_n": sw, "spot_n": sp, "oi_n": len(oi),
                         "secs": round(time.time() - t0, 1)}
        print(f"{base:5s} fund={len(fund):5d} oi={len(oi):4d} "
              f"swap={sw:5d} spot={sp:5d}  "
              f"first_fund={fund[0][0] if fund else '-'}  ({summary[base]['secs']}s)",
              flush=True)
        with open(f"{OUT}/_fetch_summary.json", "w") as f:
            json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
