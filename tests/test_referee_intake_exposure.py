"""Exposure-aware evidence handling in referee/intake.

The defect: a normal low-frequency strategy's per-bar equity is flat between
trades (no position -> 0.0 return); the intake's stale/forward-fill integrity
check read those runs as stale DATA and returned UNVERIFIABLE before the gauntlet
ever graded it. Fix (evidence handling only): when the submission carries an
exposure/position column, no-position bars are treated as structurally flat
(out of market), excluded from the stale-fill + look-ahead tells, and the
min-observations floor is applied to the ACTIVE (in-position) unit. Grading,
thresholds and signing are unchanged.

These tests pin the four required behaviours:
  * a platform backtest with flat no-position stretches now reaches a real verdict
    (not UNVERIFIABLE-by-stale-fill);
  * genuinely stale / forward-filled data still trips -> UNVERIFIABLE (both with
    exposure info, when the fill is WHILE HOLDING, and without it);
  * a strategy with too few trades returns UNVERIFIABLE-for-sample (honest);
  * the unchanged gauntlet still REJECTs a no-edge strategy.
"""
from __future__ import annotations

import numpy as np

from referee import certify as certmod
from referee import intake


def _write_returns(tmp_path, rets, positions=None, name="sub.csv"):
    p = tmp_path / name
    lines = ["return,position"] if positions is not None else ["return"]
    for i, r in enumerate(rets):
        lines.append(f"{r}," + str(positions[i]) if positions is not None else f"{r}")
    p.write_text("\n".join(lines))
    return str(p)


def _write_equity(tmp_path, rets, positions, name="eq.csv"):
    """Equity-curve CSV with positions_value — exactly the platform's shape."""
    p = tmp_path / name
    eq = 10000.0
    rows = ["timestamp,equity,positions_value"]
    # day 0 anchor (no return consumed for it)
    import datetime as dt
    base = dt.date(2023, 1, 2)
    rows.append(f"{base},{eq},{positions[0]}")
    for i, r in enumerate(rets):
        eq *= (1.0 + r)
        day = base + dt.timedelta(days=i + 1)
        rows.append(f"{day},{eq},{positions[i]}")
    p.write_text("\n".join(rows))
    return str(p)


# --------------------------------------------------------------------------
# 1) Platform flat strategy -> a REAL verdict, not UNVERIFIABLE-by-stale-fill
# --------------------------------------------------------------------------
def test_flat_no_position_strategy_reaches_real_verdict(tmp_path):
    rng = np.random.default_rng(0)
    rets, pos = [], []
    # 4 idle runs of 50 flat bars (longest run 50 >> the 10%-of-320 = 32 floor)
    # interleaved with 30-bar active blocks -> 120 active bars total.
    for _ in range(4):
        rets += [0.0] * 50;                       pos += [0] * 50
        rets += list(rng.normal(0.0, 0.01, 30));  pos += [1000.0] * 30
    csv = _write_equity(tmp_path, rets, pos)
    sub = intake.parse_submission(csv, cost_bps=15, declared_trials=4)
    integ = intake.check_integrity(sub)
    verd = certmod.certify(sub)

    assert integ["status"] != "UNVERIFIABLE", integ["reasons"]
    assert not any("stale" in r for r in integ["reasons"])
    assert verd["verdict"] in {"DEPLOY", "HOLD_CONDITIONAL", "REJECT"}
    # min-obs floor was applied to the active unit, and there were enough.
    assert integ["metrics"]["n_active_obs"] >= intake.MIN_OBS


# --------------------------------------------------------------------------
# 2) Genuinely stale / forward-filled data still trips
# --------------------------------------------------------------------------
def test_stale_fill_while_holding_still_unverifiable(tmp_path):
    """Forward-filled returns WHILE IN POSITION are real stale data -> caught,
    even though an exposure column is present."""
    rng = np.random.default_rng(1)
    rets = list(rng.normal(0.0, 0.01, 100)) + [0.0049] * 80 + list(rng.normal(0.0, 0.01, 100))
    pos = [1000.0] * len(rets)                      # always in the market
    csv = _write_returns(tmp_path, rets, pos)
    integ = intake.check_integrity(intake.parse_submission(csv, cost_bps=10, declared_trials=1))
    assert integ["status"] == "UNVERIFIABLE"
    assert any("stale" in r for r in integ["reasons"]), integ["reasons"]


def test_stale_fill_without_exposure_unchanged(tmp_path):
    """A bare submission (no exposure column) keeps the original behaviour: a long
    identical-return run is flagged stale. No silent weakening."""
    rng = np.random.default_rng(2)
    rets = list(rng.normal(0.0, 0.01, 100)) + [0.0] * 80 + list(rng.normal(0.0, 0.01, 100))
    csv = _write_returns(tmp_path, rets)            # no position column
    sub = intake.parse_submission(csv, cost_bps=10, declared_trials=1)
    assert sub.in_position is None
    integ = intake.check_integrity(sub)
    assert integ["status"] == "UNVERIFIABLE"
    assert any("stale" in r for r in integ["reasons"]), integ["reasons"]


# --------------------------------------------------------------------------
# 3) Too few trades -> UNVERIFIABLE-for-sample (the honest reason)
# --------------------------------------------------------------------------
def test_too_few_active_observations_is_unverifiable_for_sample(tmp_path):
    rng = np.random.default_rng(3)
    rets = [0.0] * 200 + list(rng.normal(0.0, 0.01, 20)) + [0.0] * 100
    pos = [0] * 200 + [1000.0] * 20 + [0] * 100
    csv = _write_equity(tmp_path, rets, pos)
    integ = intake.check_integrity(intake.parse_submission(csv, cost_bps=15, declared_trials=1))
    assert integ["status"] == "UNVERIFIABLE"
    assert any("active (in-position) observations" in r for r in integ["reasons"]), integ["reasons"]
    # the false stale-fill reason must NOT be why it failed
    assert not any("stale" in r for r in integ["reasons"])


# --------------------------------------------------------------------------
# 4) Unchanged gauntlet still REJECTs a no-edge strategy
# --------------------------------------------------------------------------
def test_no_edge_strategy_still_rejects(tmp_path):
    rng = np.random.default_rng(7)
    rets = list(rng.normal(-0.0003, 0.01, 300))     # slight negative drift, no edge
    csv = _write_returns(tmp_path, rets)            # bare returns, fully active by nature
    sub = intake.parse_submission(csv, cost_bps=10, declared_trials=1)
    integ = intake.check_integrity(sub)
    assert integ["status"] != "UNVERIFIABLE", integ["reasons"]
    assert certmod.certify(sub)["verdict"] == "REJECT"
