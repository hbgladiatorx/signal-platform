#!/usr/bin/env python3
"""Phase-0 deep-history fetcher via data.binance.vision (static dumps, NOT
geo-blocked — the live fapi API is). Pulls Binance USDT-perp funding-rate
history 2024-01 .. current month for the majors, concatenated to one CSV/symbol.

Funding is the novel alpha signal. We trade Binance.US USD spot long/flat; funding
is a venue-agnostic predictor (Binance is the dominant venue, best signal source).
Output: app/logs/perp/<BASE>_funding_full.csv  (ts_ms, funding, interval_hrs)
"""
import os, sys, csv, io, zipfile, time, json
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

OUT = "/home/signal/app/logs/perp"
os.makedirs(OUT, exist_ok=True)
BASE = "https://data.binance.vision/data/futures/um"
SYMBOLS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "LINK", "AVAX", "LTC"]

# build month list 2024-01 .. 2026-06 (current). No Date.now in scripts; hardcode end.
MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025, 2026) for m in range(1, 13)
          if not (y == 2026 and m > 6)]
# current month (2026-06) only has daily dumps, not monthly yet -> fetch dailies.
CURRENT_MONTH = "2026-06"
CURRENT_DAYS = [f"2026-06-{d:02d}" for d in range(1, 25)]  # through 2026-06-24


def fetch_zip_csv(url):
    for i in range(4):
        try:
            with urlopen(Request(url, headers={"User-Agent": "phase0/1.0"}), timeout=30) as r:
                blob = r.read()
            z = zipfile.ZipFile(io.BytesIO(blob))
            name = z.namelist()[0]
            return list(csv.reader(io.TextIOWrapper(z.open(name), "utf-8")))
        except HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1.0 * (i + 1))
        except (URLError, zipfile.BadZipFile):
            time.sleep(1.0 * (i + 1))
    return None


def parse_rows(rows):
    """funding dump cols: calc_time, funding_interval_hours, last_funding_rate."""
    out = []
    for r in rows:
        if not r or r[0].startswith("calc_time"):
            continue
        try:
            out.append((int(r[0]), float(r[2]), int(float(r[1]))))
        except (ValueError, IndexError):
            continue
    return out


def main():
    only = sys.argv[1:] or None
    summary = {}
    for base in SYMBOLS:
        if only and base not in only:
            continue
        sym = f"{base}USDT"
        t0, rows, miss = time.time(), [], 0
        for mo in MONTHS:
            if mo == CURRENT_MONTH:
                continue
            data = fetch_zip_csv(f"{BASE}/monthly/fundingRate/{sym}/{sym}-fundingRate-{mo}.zip")
            if data is None:
                miss += 1
                continue
            rows.extend(parse_rows(data))
        for day in CURRENT_DAYS:
            data = fetch_zip_csv(f"{BASE}/daily/fundingRate/{sym}/{sym}-fundingRate-{day}.zip")
            if data:
                rows.extend(parse_rows(data))
        rows = sorted(set(rows))
        path = f"{OUT}/{base}_funding_full.csv"
        with open(path, "w") as f:
            f.write("ts_ms,funding,interval_hrs\n")
            for ts, fr, iv in rows:
                f.write(f"{ts},{fr},{iv}\n")
        summary[base] = {"n": len(rows), "first": rows[0][0] if rows else None,
                         "last": rows[-1][0] if rows else None,
                         "missing_months": miss, "secs": round(time.time() - t0, 1)}
        print(f"{base:5s} n={len(rows):5d} miss_mo={miss:2d} "
              f"first={rows[0][0] if rows else '-'} last={rows[-1][0] if rows else '-'} "
              f"({summary[base]['secs']}s)", flush=True)
        with open(f"{OUT}/_funding_summary.json", "w") as f:
            json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
