#!/usr/bin/env python3
"""Phase-0 OHLCV integrity audit for the cross-sectional universe (xr_1h.csv).

Pure stdlib (no numpy) so it runs anywhere. The cross-sectional ranker is only
as trustworthy as the bars it ranks: one symbol with stale forward-fills or
artifact jumps will dominate a trailing-return ranking and manufacture a false
"strongest". Audits the failure modes that corrupt a momentum rank:

  1. CONTINUITY   - missing hourly bars, duplicate / non-monotonic timestamps,
                    coverage vs the expected hourly grid.
  2. BAD TICKS    - non-positive prices, high<low, OHLC inconsistency.
  3. ARTIFACT JUMPS - implausible 1h close-to-close moves (the BCH-1h analogue
                    the referee memory flagged: ann Sharpe 2.7-5.2 = data artifact).
  4. STALENESS    - long runs of identical consecutive closes (illiquid /
                    forward-filled => fake zero-vol then jump, poisons momentum).

Verdict per symbol: CLEAN / FLAG / DROP. DROP if any disqualifying condition.
Emits app/logs/xsec_data_integrity.json and prints a readable report.
"""
import csv, json, collections
from datetime import datetime, timezone

XR = "/home/signal/app/logs/xr_1h.csv"
OUT = "/home/signal/app/logs/xsec_data_integrity.json"
H1_MS = 3600 * 1000

ID2BASE = {15: "ADA", 44: "AVAX", 12: "BCH", 14: "BNB", 1: "BTC", 20: "DOGE",
           46: "DOT", 2: "ETH", 53: "LINK", 13: "LTC", 6: "SOL", 11: "XRP"}

# disqualifying thresholds (pre-registered, conservative)
JUMP_ABS = 0.50           # a single 1h close-to-close move > 50% on a liquid major = artifact
DROP_IF_JUMPS_GT = 0      # any >50% 1h move => DROP (majors do not move 50% in 1h cleanly)
DROP_IF_STALE_RUN_GT = 12  # >12 identical consecutive 1h closes (>=12h frozen) => illiquid/ffill
DROP_IF_COVERAGE_LT = 99.0  # <99% of expected hourly grid => too gappy to rank
FLAG_JUMP_ABS = 0.25       # 25-50% 1h moves are flagged (watch), not auto-dropped


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=timezone.utc) \
        if "T" in s or "+" in s else datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def audit():
    rows_by_id = collections.defaultdict(list)
    with open(XR) as f:
        r = csv.DictReader(f)
        for row in r:
            iid = int(row["instrument_id"])
            if iid not in ID2BASE:
                continue
            rows_by_id[iid].append((row["bucket"],
                                    float(row["open"]), float(row["high"]),
                                    float(row["low"]), float(row["close"]),
                                    float(row["volume"])))
    reports = []
    for iid, base in sorted(ID2BASE.items(), key=lambda kv: kv[1]):
        rows = sorted(rows_by_id.get(iid, []), key=lambda x: x[0])
        rep = {"symbol": base, "instrument_id": iid, "n": len(rows)}
        if len(rows) < 500:
            rep.update(verdict="DROP", reasons=["insufficient rows"])
            reports.append(rep)
            continue
        ts = [parse_ts(x[0]) for x in rows]
        tms = [int(t.timestamp() * 1000) for t in ts]
        o = [x[1] for x in rows]; h = [x[2] for x in rows]
        lo = [x[3] for x in rows]; c = [x[4] for x in rows]; v = [x[5] for x in rows]

        # --- continuity ---
        dups = sum(1 for i in range(1, len(tms)) if tms[i] == tms[i-1])
        nonmono = sum(1 for i in range(1, len(tms)) if tms[i] < tms[i-1])
        span = tms[-1] - tms[0]
        expected = round(span / H1_MS) + 1
        coverage = round(100 * len(rows) / expected, 3)
        deltas = [tms[i] - tms[i-1] for i in range(1, len(tms))]
        gaps = sum(1 for d in deltas if d > H1_MS * 1.5)
        biggest_gap_h = round(max(deltas, default=0) / H1_MS, 1)

        # --- bad ticks ---
        nonpos = sum(1 for x in c if x <= 0) + sum(1 for x in o if x <= 0)
        hl_bad = sum(1 for i in range(len(c)) if h[i] < lo[i])
        ohlc_bad = sum(1 for i in range(len(c))
                       if h[i] < max(o[i], c[i]) - 1e-9 or lo[i] > min(o[i], c[i]) + 1e-9)

        # --- artifact jumps (close-to-close) ---
        rets = [(c[i] / c[i-1] - 1.0) if c[i-1] > 0 else 0.0 for i in range(1, len(c))]
        big_jumps = [(rows[i+1][0][:13], round(rets[i], 4))
                     for i in range(len(rets)) if abs(rets[i]) > JUMP_ABS]
        flag_jumps = sum(1 for x in rets if FLAG_JUMP_ABS < abs(x) <= JUMP_ABS)
        max_abs_ret = round(max((abs(x) for x in rets), default=0.0), 4)

        # --- staleness ---
        run = 1; max_run = 1; max_run_at = rows[0][0][:10]
        for i in range(1, len(c)):
            if c[i] == c[i-1]:
                run += 1
                if run > max_run:
                    max_run, max_run_at = run, rows[i][0][:10]
            else:
                run = 1
        zero_vol = sum(1 for x in v if x == 0)

        rep.update(
            coverage_pct=coverage, expected_bars=expected, gap_count=gaps,
            biggest_gap_hrs=biggest_gap_h, duplicate_ts=dups, non_monotonic=nonmono,
            nonpos_price=nonpos, high_lt_low=hl_bad, ohlc_inconsistent=ohlc_bad,
            max_abs_1h_ret=max_abs_ret, artifact_jumps_gt50pct=len(big_jumps),
            artifact_jump_sample=big_jumps[:6], flag_jumps_25to50pct=flag_jumps,
            max_identical_close_run=max_run, max_identical_run_at=max_run_at,
            zero_volume_bars=zero_vol,
            date_min=rows[0][0][:10], date_max=rows[-1][0][:10])

        reasons = []
        if coverage < DROP_IF_COVERAGE_LT:
            reasons.append(f"coverage {coverage}% < {DROP_IF_COVERAGE_LT}%")
        if dups or nonmono:
            reasons.append(f"dup/nonmono ts ({dups}/{nonmono})")
        if nonpos or hl_bad or ohlc_bad:
            reasons.append(f"bad ticks (nonpos={nonpos},hl={hl_bad},ohlc={ohlc_bad})")
        if len(big_jumps) > DROP_IF_JUMPS_GT:
            reasons.append(f"{len(big_jumps)} artifact jumps >50%/1h")
        if max_run > DROP_IF_STALE_RUN_GT:
            reasons.append(f"stale run {max_run} identical closes")
        flags = []
        if flag_jumps:
            flags.append(f"{flag_jumps} jumps 25-50%/1h")
        rep["verdict"] = "DROP" if reasons else ("FLAG" if flags else "CLEAN")
        rep["reasons"] = reasons
        rep["flags"] = flags
        reports.append(rep)
    return reports


def main():
    reports = audit()
    clean = [r["symbol"] for r in reports if r["verdict"] in ("CLEAN", "FLAG")]
    dropped = [r["symbol"] for r in reports if r["verdict"] == "DROP"]
    out = {"file": XR, "n_symbols_audited": len(reports),
           "thresholds": {"jump_abs": JUMP_ABS, "drop_stale_run_gt": DROP_IF_STALE_RUN_GT,
                          "drop_coverage_lt": DROP_IF_COVERAGE_LT},
           "kept": clean, "dropped": dropped, "symbols": reports}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print("=" * 78)
    print("XSEC UNIVERSE INTEGRITY AUDIT  (xr_1h.csv, 12 candidate majors)")
    print("=" * 78)
    print(f"{'sym':5}{'verdict':9}{'n':>7}{'cov%':>8}{'gaps':>6}{'maxJump':>9}"
          f"{'>50%':>6}{'25-50%':>8}{'staleRun':>10}  reasons")
    for r in reports:
        print(f"{r['symbol']:5}{r['verdict']:9}{r['n']:>7}{r.get('coverage_pct',0):>8.2f}"
              f"{r.get('gap_count',0):>6}{r.get('max_abs_1h_ret',0):>9.3f}"
              f"{r.get('artifact_jumps_gt50pct',0):>6}{r.get('flag_jumps_25to50pct',0):>8}"
              f"{r.get('max_identical_close_run',0):>10}  "
              f"{';'.join(r.get('reasons',[]) or r.get('flags',[]))}")
    print("-" * 78)
    print(f"KEPT ({len(clean)}): {', '.join(clean)}")
    print(f"DROPPED ({len(dropped)}): {', '.join(dropped) or 'none'}")
    print(f"\nreport -> {OUT}")


if __name__ == "__main__":
    main()
