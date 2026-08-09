#!/usr/bin/env python3
"""Phase-0 funding-data integrity audit for app/logs/perp/*_funding_full.csv.

Pure stdlib (no numpy) so it runs anywhere. Audits the four failure modes that
would silently invert or look-ahead-leak a funding-gated backtest:

  1. SIGN convention   - positive funding == longs pay shorts? cross-checked
                         against known capitulation dates (negative spikes
                         must land on crash days, not rally days).
  2. SETTLEMENT/ALIGN  - every ts aligned to the funding clock; interval never
                         silently switches 8h<->4h mid-history (Binance did this
                         for some symbols); spacing == declared interval.
  3. CONTINUITY        - no missing settlements, no duplicate timestamps, no
                         stale forward-fill runs (identical consecutive values).
  4. PLAUSIBILITY      - flag implausible spikes (the BCH-1h analogue) beyond
                         Binance's funding clamp.

Emits app/logs/funding_data_integrity.json and prints a readable report.
"""
import csv, json, glob, os
from datetime import datetime, timezone

PERP = "/home/signal/app/logs/perp"
OUT = "/home/signal/app/logs/funding_data_integrity.json"
H8_MS = 8 * 3600 * 1000
H4_MS = 4 * 3600 * 1000

# Known crypto capitulation / crash windows (UTC dates). On these days perps
# are short-crowded -> shorts pay longs -> funding should print NEGATIVE if the
# sign convention is "positive == longs pay shorts".
KNOWN_CRASHES = {
    "2024-08-05": "yen carry unwind, global risk crash",
    "2025-02-03": "tariff-shock weekend gap",
    "2025-04-07": "april tariff crash",
}
# Known euphoria / rally windows -> longs crowded -> funding strongly POSITIVE.
KNOWN_RALLIES = {
    "2024-03": "BTC new ATH run",
    "2024-11": "post-US-election melt-up",
    "2024-12": "BTC 100k breakout",
}

def to_utc(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

def day(ts_ms):
    return to_utc(ts_ms).strftime("%Y-%m-%d")

def audit_symbol(path):
    sym = os.path.basename(path).split("_")[0]
    rows = []
    with open(path) as f:
        r = csv.reader(f)
        next(r, None)  # header
        for line in r:
            if len(line) < 3:
                continue
            rows.append((int(line[0]), float(line[1]), int(float(line[2]))))
    rep = {"symbol": sym, "n": len(rows)}
    if not rows:
        rep["fatal"] = "no rows"
        return rep

    ts = [x[0] for x in rows]
    fund = [x[1] for x in rows]
    ivl = [x[2] for x in rows]

    # --- monotonic + duplicate timestamps ---
    dups = sum(1 for i in range(1, len(ts)) if ts[i] == ts[i-1])
    nonmono = sum(1 for i in range(1, len(ts)) if ts[i] < ts[i-1])
    rep["duplicate_ts"] = dups
    rep["non_monotonic"] = nonmono

    # --- interval column: does it ever switch? ---
    ivl_counts = {}
    for v in ivl:
        ivl_counts[v] = ivl_counts.get(v, 0) + 1
    rep["interval_hrs_distribution"] = ivl_counts

    # --- alignment to funding clock ---
    # tolerate small ms jitter (<=5s); flag anything larger as a real shift
    misalign = []
    for t in ts:
        off = t % H8_MS
        off = min(off, H8_MS - off)  # distance to nearest 8h boundary
        if off > 5000:
            misalign.append(off)
    rep["misaligned_gt5s"] = len(misalign)
    rep["max_align_offset_ms"] = max((t % H8_MS for t in ts), default=0)
    # how many carry the trailing few-ms quirk
    rep["nonzero_ms_offset"] = sum(1 for t in ts if t % 1000 != 0)

    # --- spacing / continuity ---
    deltas = [ts[i] - ts[i-1] for i in range(1, len(ts))]
    delta_counts = {}
    for d in deltas:
        # bucket to nearest second to absorb the 4ms jitter
        key = round(d / 1000) * 1000
        delta_counts[key] = delta_counts.get(key, 0) + 1
    rep["spacing_ms_distribution"] = dict(sorted(delta_counts.items(), key=lambda kv: -kv[1])[:6])
    # gaps = any spacing materially > 8h (missing settlements)
    gaps = [(day(ts[i-1]), round(deltas[i-1]/H8_MS, 2)) for i in range(1, len(ts))
            if deltas[i-1] > H8_MS * 1.5]
    rep["gap_count"] = len(gaps)
    rep["gaps_sample"] = gaps[:10]
    # expected count over span at 8h
    span = ts[-1] - ts[0]
    rep["expected_n_at_8h"] = round(span / H8_MS) + 1
    rep["coverage_pct"] = round(100 * len(rows) / (round(span / H8_MS) + 1), 2)

    # --- stale forward-fill detection: identical consecutive funding ---
    run = 1
    max_run = 1
    max_run_at = None
    for i in range(1, len(fund)):
        if fund[i] == fund[i-1]:
            run += 1
            if run > max_run:
                max_run, max_run_at = run, day(ts[i])
        else:
            run = 1
    rep["max_identical_run"] = max_run
    rep["max_identical_run_at"] = max_run_at

    # --- plausibility ---
    n = len(fund)
    mean = sum(fund) / n
    var = sum((x - mean) ** 2 for x in fund) / n
    std = var ** 0.5
    rep["funding_mean_8h"] = mean
    rep["funding_std_8h"] = std
    rep["funding_min"] = min(fund)
    rep["funding_max"] = max(fund)
    rep["pct_positive"] = round(100 * sum(1 for x in fund if x > 0) / n, 2)
    rep["annualized_mean_pct"] = round(mean * 3 * 365 * 100, 2)  # 3 settlements/day
    # Binance clamp for majors is +/-0.75%/8h; flag beyond 1%
    extreme = [(day(ts[i]), fund[i]) for i in range(n) if abs(fund[i]) > 0.01]
    rep["extreme_gt_1pct_count"] = len(extreme)
    rep["extreme_sample"] = extreme[:8]

    # --- sign-convention cross-check ---
    order = sorted(range(n), key=lambda i: fund[i])
    rep["most_negative"] = [(day(ts[i]), round(fund[i], 6)) for i in order[:6]]
    rep["most_positive"] = [(day(ts[i]), round(fund[i], 6)) for i in order[-6:][::-1]]
    # do the negative extremes land near known crashes?
    neg_days = {day(ts[i]) for i in order[:15]}
    hits = []
    for cd in KNOWN_CRASHES:
        # within +/-1 day
        cd_dt = datetime.strptime(cd, "%Y-%m-%d").date()
        for nd in neg_days:
            nd_dt = datetime.strptime(nd, "%Y-%m-%d").date()
            if abs((nd_dt - cd_dt).days) <= 1:
                hits.append((cd, KNOWN_CRASHES[cd]))
                break
    rep["neg_extremes_match_known_crashes"] = hits
    return rep


def main():
    paths = sorted(glob.glob(f"{PERP}/*_funding_full.csv"))
    reports = [audit_symbol(p) for p in paths]
    out = {"files_audited": len(paths), "symbols": reports}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)

    # readable print
    for r in reports:
        s = r["symbol"]
        print(f"\n===== {s} =====")
        print(f"  n={r['n']}  span_expected={r.get('expected_n_at_8h')}  coverage={r.get('coverage_pct')}%")
        print(f"  interval_hrs={r['interval_hrs_distribution']}  dup_ts={r['duplicate_ts']}  non_mono={r['non_monotonic']}")
        print(f"  spacing(ms,top)={r['spacing_ms_distribution']}")
        print(f"  gaps>1.5x8h={r['gap_count']}  sample={r['gaps_sample'][:3]}")
        print(f"  align: misaligned>5s={r['misaligned_gt5s']}  max_offset_ms={r['max_align_offset_ms']}  nonzero_ms={r['nonzero_ms_offset']}")
        print(f"  stale: max_identical_run={r['max_identical_run']} at {r['max_identical_run_at']}")
        print(f"  funding: mean8h={r['funding_mean_8h']:.6e} std={r['funding_std_8h']:.6e} "
              f"min={r['funding_min']:.4e} max={r['funding_max']:.4e}")
        print(f"  pct_positive={r['pct_positive']}%  annualized_mean={r['annualized_mean_pct']}%")
        print(f"  extreme>1%: {r['extreme_gt_1pct_count']}  sample={r['extreme_sample'][:3]}")
        print(f"  most_negative={r['most_negative'][:4]}")
        print(f"  most_positive={r['most_positive'][:4]}")
        print(f"  neg_extremes match known crashes: {r['neg_extremes_match_known_crashes']}")
    print(f"\nReport -> {OUT}")


if __name__ == "__main__":
    main()
