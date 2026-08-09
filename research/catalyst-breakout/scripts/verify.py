#!/usr/bin/env python3
"""Stdlib-only verification harness (no pytest required).

Runs the same anti-bias checks as tests/ against the REAL code paths, plus an
end-to-end backtest that produces a segmented report. Use this to prove the
system works in environments without pytest:

    python scripts/verify.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from catalyst.store.db import Database
from catalyst.store.panel import AsOfPanel, LookaheadError
from catalyst.pit.features import get_pit_features
from catalyst.backtest.engine import run_signal, Trade
from catalyst.backtest import report
from catalyst.testing import synth
from config.defaults import DEFAULTS

PASS, FAIL = 0, 0


def check(name: str, cond: bool):
    global PASS, FAIL
    mark = "PASS" if cond else "FAIL"
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{mark}] {name}")


def fresh_db() -> Database:
    d = Database("sqlite:///:memory:")
    d.bootstrap()
    return d


def t_no_lookahead():
    print("\n# Rule 1 -- no lookahead")
    db = fresh_db()
    synth.seed_prices(db, "SYNA", date(2022, 1, 3), [10 + i * 0.1 for i in range(40)])
    as_of = date(2022, 1, 3) + timedelta(days=20)
    hist = AsOfPanel(db, as_of).price_history("SYNA")
    check("no price bar after as_of", all(r["date"] <= as_of.isoformat() for r in hist))

    synth.seed_catalyst(db, "SYNC", knowable_at=date(2023, 9, 20))
    synth.seed_catalyst(db, "SYNC", knowable_at=date(2023, 8, 25))
    seen = {c["knowable_at"] for c in AsOfPanel(db, date(2023, 9, 1)).catalysts("SYNC")}
    check("future catalyst invisible", "2023-09-20" not in seen and "2023-08-25" in seen)

    try:
        AsOfPanel(db, date(2022, 1, 1))._assert_no_future([{"date": "2025-01-01"}], "date")
        check("lookahead guard raises", False)
    except LookaheadError:
        check("lookahead guard raises", True)
    db.close()


def t_pit_fundamentals():
    print("\n# Rule 4 -- PIT fundamentals lagged to filing")
    db = fresh_db()
    synth.seed_prices(db, "SYNF", date(2022, 1, 3), [10.0] * 300)
    synth.seed_universe(db, "SYNF", date(2022, 1, 3))
    synth.seed_fundamentals(db, "SYNF", period_end=date(2022, 3, 31),
                            knowable_at=date(2022, 5, 6), fcf=99.0)
    before = AsOfPanel(db, date(2022, 4, 15)).fundamentals("SYNF")
    after = AsOfPanel(db, date(2022, 5, 10)).fundamentals("SYNF")
    check("quarter hidden before filing", not any(f["period_end"] == "2022-03-31" for f in before))
    check("quarter visible after filing", any(f["period_end"] == "2022-03-31" for f in after))
    db.close()


def t_survivorship():
    print("\n# Rule 3 -- survivorship")
    db = fresh_db()
    as_of = date(2020, 6, 1)
    synth.seed_universe(db, "SURV", date(2020, 1, 2))
    synth.seed_universe(db, "DEAD", date(2020, 1, 2), delisted_date=date(2021, 3, 15))
    synth.seed_universe(db, "NEWB", date(2021, 1, 4))
    tickers = {u["ticker"] for u in AsOfPanel(db, as_of).universe()}
    check("later-delisted name retained", "DEAD" in tickers)
    check("survivor retained", "SURV" in tickers)
    check("future member excluded", "NEWB" not in tickers)
    db.close()


def t_next_bar():
    print("\n# Rule 2 -- next-bar entry + do-not-chase at T+1")
    db = fresh_db()
    as_of = synth.seed_firing_name(db, "SYND", date(2022, 1, 3))
    trade = run_signal(db, "SYND", as_of, cfg=DEFAULTS)
    check("signal fired and filled", trade is not None and trade.filled)
    check("entry is T+1", trade.entry_date == (as_of + timedelta(days=1)).isoformat())
    check("entry strictly after signal", trade.entry_date > trade.signal_date)

    # Gap-up name: the T+1 OPEN gaps far above the do-not-chase level -> no fill.
    db2 = fresh_db()
    start = date(2022, 1, 3)
    closes = [40.0] * 256 + [80.0, 80.0, 80.0, 80.0]
    # Flat opens on the base; the bar AFTER the signal opens at 80 (a real gap).
    opens = [40.0] * 256 + [80.0, 80.0, 80.0, 80.0]
    synth.seed_prices(db2, "SYNG", start, closes, opens=opens)
    synth.seed_universe(db2, "SYNG", start, market_cap=1_000_000_000.0)
    for i, (fcf, m) in enumerate([(1, .01), (2, .02), (3, .04), (5, .08)]):
        synth.seed_fundamentals(db2, "SYNG", start + timedelta(days=i),
                                start + timedelta(days=i), fcf=fcf, op_margin=m)
    synth.seed_iv(db2, "SYNG", start, [0.4] * len(closes))
    gas = start + timedelta(days=255)  # signal on last base bar; entry bar gaps to 80
    synth.seed_catalyst(db2, "SYNG", knowable_at=gas,
                        payload={"surprise_pct": 12.0, "guidance_raise": True})
    gtrade = run_signal(db2, "SYNG", gas, cfg=DEFAULTS)
    check("gap-up blocked by do-not-chase",
          gtrade is not None and not gtrade.filled and gtrade.no_fill_reason == "do_not_chase")
    db.close()
    db2.close()


def t_archetype_neutral():
    print("\n# Rule 6 -- archetype not scored / treated identically")
    import re
    src = ROOT / "src" / "catalyst"
    offenders = []
    for pkg in ("screen", "catalysts", "options", "signals", "backtest", "pit"):
        for py in (src / pkg).rglob("*.py"):
            text = py.read_text()
            for name in DEFAULTS.archetype_names:
                if re.search(rf"\b{name}\b", text):
                    offenders.append(f"{py.name}:{name}")
    check("no archetype literals in decision path", not offenders)

    db = fresh_db()
    a = synth.seed_firing_name(db, "INTC", date(2022, 1, 3))
    synth.seed_firing_name(db, "ZZZZ", date(2022, 1, 3))
    ta = run_signal(db, "INTC", a, cfg=DEFAULTS)
    tc = run_signal(db, "ZZZZ", a, cfg=DEFAULTS)
    check("archetype == synthetic control",
          ta.filled == tc.filled and abs((ta.rules_return or 0) - (tc.rules_return or 0)) < 1e-9)
    db.close()


def t_min_n_report():
    print("\n# Validation gate -- min-N suppression + segmentation")

    def mk(ct, d, ret=0.15):
        return Trade("SYN", d, d, 10.0, True, "", ct, "structured", False,
                     {3: ret, 6: ret, 12: ret}, ret, "target_3", 30)

    under = report.generate([mk("federal_award", "2024-01-15") for _ in range(5)], DEFAULTS)
    check("under-N bucket suppressed", under["by_catalyst"]["federal_award"].reported is False)

    from dataclasses import replace
    cfg = replace(DEFAULTS, backtest=replace(DEFAULTS.backtest, min_trades_per_bucket=20))
    over = report.generate([mk("earnings_surprise_guidance_raise", "2024-02-01")
                            for _ in range(25)], cfg)
    b = over["by_catalyst"]["earnings_surprise_guidance_raise"]
    check("at/over-N bucket reported", b.reported and b.rules_stats.n == 25)

    cfg1 = replace(DEFAULTS, backtest=replace(DEFAULTS.backtest, min_trades_per_bucket=1))
    regimes = report.generate(
        [mk("earnings_surprise_guidance_raise", "2019-06-01") for _ in range(3)]
        + [mk("earnings_surprise_guidance_raise", "2024-06-01") for _ in range(3)], cfg1)
    check("segments by regime", len(regimes["by_regime"]) >= 2)


def t_end_to_end():
    print("\n# End-to-end backtest -> report")
    db = fresh_db()
    # 30 synthetic firing names across two regimes.
    sigs = []
    for i in range(30):
        tk = f"SYN{i:02d}"
        start = date(2019, 1, 2) if i < 15 else date(2024, 1, 2)
        as_of = synth.seed_firing_name(db, tk, start)
        sigs.append((tk, as_of))
    trades = [run_signal(db, tk, ao, cfg=DEFAULTS) for tk, ao in sigs]
    trades = [t for t in trades if t is not None]
    check("end-to-end produced trades", len(trades) > 0)
    from dataclasses import replace
    cfg = replace(DEFAULTS, backtest=replace(DEFAULTS.backtest, min_trades_per_bucket=5))
    rep = report.generate(trades, cfg)
    print(report.render_text(rep))
    db.close()


def main():
    print("=" * 70)
    print("CATALYST BREAKOUT -- VERIFICATION HARNESS (stdlib only)")
    print("=" * 70)
    for fn in (t_no_lookahead, t_pit_fundamentals, t_survivorship, t_next_bar,
               t_archetype_neutral, t_min_n_report, t_end_to_end):
        fn()
    print("\n" + "=" * 70)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
