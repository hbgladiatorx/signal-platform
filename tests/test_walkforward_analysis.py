"""Tests for the walk-forward (validation / OOS) verdict.

The defect: the OOS stage dead-ended in raw metrics. analyze_walkforward adds a
legible verdict ON TOP of the metrics the engine already computes — no validation
math is touched. These tests pin down:

  * a failing OOS result -> REJECT-style verdict with a populated what-to-fix
    list and a non-empty, actionable path-back;
  * a passing OOS result -> DEPLOY-style verdict;
  * the verdict is present in the response schema and flows through the router's
    response model;
  * the shape matches the referee verdict structure (call words + narrative +
    metrics), reusing the gauntlet vocabulary rather than inventing a new one.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from packages.analysis import analyze_walkforward
from packages.analysis.walkforward_analysis import VERDICTS

# The referee gauntlet's verdict vocabulary (referee/certify.py). The studio OOS
# verdict must speak exactly these words — one verdict language end to end.
REFEREE_VERDICTS = {"DEPLOY", "HOLD_CONDITIONAL", "REJECT", "UNVERIFIABLE"}
# The referee cert record's core keys (referee/certify.py base + update).
REFEREE_CORE_KEYS = {"verdict", "narrative", "metrics"}


def _row(**over) -> dict:
    """A completed walk-forward row with healthy defaults; override per-test."""
    base = {
        "status": "completed",
        "strategy_name": "SPY RSI MR",
        "avg_train_sharpe": 1.3,
        "avg_test_sharpe": 1.1,
        "overfit_drop": 0.2,
        "avg_test_return_pct": 4.5,
        "win_rate_windows_pct": 80.0,
        "num_windows": 6,
        "total_combos": 4,
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------
# Verdict derivation
# --------------------------------------------------------------------------
def test_failing_oos_is_reject_with_fixes_and_path_back():
    v = analyze_walkforward(_row(avg_test_sharpe=-0.3, avg_test_return_pct=-2.0,
                                 overfit_drop=1.6))
    assert v is not None
    assert v["verdict"] == "REJECT"
    # Ranked what-to-fix list is populated...
    assert len(v["findings"]) >= 1
    assert all({"cluster", "severity", "title", "suggestion"} <= set(f) for f in v["findings"])
    # ...worst-first (bad before warn/good).
    sev_order = {"bad": 0, "warn": 1, "good": 2, "info": 3}
    ranks = [sev_order[f["severity"]] for f in v["findings"]]
    assert ranks == sorted(ranks)
    # The path back is actionable, not a dead string.
    na = v["next_action"]
    assert na["action"] == "edit_strategy"
    assert na["label"].strip()
    assert na["target"] == "studio.strategies"
    assert na["strategy_name"] == "SPY RSI MR"
    # The cost-wall vocabulary is reused for net-negative-but-not-noise cases.
    clusters = {f["cluster"] for f in v["findings"]}
    assert "no_signal" in clusters  # test Sharpe <= 0 dominates here


def test_cost_wall_reject_uses_referee_cluster():
    # Risk-adjusted positive but net return negative = the referee cost-wall cluster.
    v = analyze_walkforward(_row(avg_test_sharpe=0.4, avg_test_return_pct=-1.0))
    assert v["verdict"] == "REJECT"
    assert any(f["cluster"] == "gross_pos_net_neg" for f in v["findings"])


def test_passing_oos_is_deploy():
    v = analyze_walkforward(_row())
    assert v["verdict"] == "DEPLOY"
    assert v["next_action"]["action"] == "deploy"
    assert v["next_action"]["target"] == "studio.live"
    assert any(f["severity"] == "good" for f in v["findings"])


def test_overfit_positive_is_hold_conditional():
    v = analyze_walkforward(_row(overfit_drop=1.2))  # positive OOS but overfit
    assert v["verdict"] == "HOLD_CONDITIONAL"
    assert any(f["cluster"] == "deflation_collapse" for f in v["findings"])
    assert v["next_action"]["action"] == "edit_strategy"


def test_single_regime_positive_is_hold_conditional():
    v = analyze_walkforward(_row(win_rate_windows_pct=40.0))
    assert v["verdict"] == "HOLD_CONDITIONAL"
    assert any(f["cluster"] == "single_regime" for f in v["findings"])


def test_completed_without_oos_is_unverifiable():
    v = analyze_walkforward(_row(avg_test_sharpe=None, avg_test_return_pct=None,
                                 num_windows=0))
    assert v["verdict"] == "UNVERIFIABLE"
    assert v["next_action"]["action"] == "edit_strategy"
    assert len(v["findings"]) >= 1


def test_unfinished_run_has_no_verdict_yet():
    assert analyze_walkforward(_row(status="running")) is None
    assert analyze_walkforward(_row(status="pending")) is None


# --------------------------------------------------------------------------
# Shape matches the referee verdict structure (one vocabulary, not a new one)
# --------------------------------------------------------------------------
def test_shape_matches_referee_verdict():
    for over in ({}, {"avg_test_sharpe": -1.0, "avg_test_return_pct": -3.0},
                 {"overfit_drop": 1.2}):
        v = analyze_walkforward(_row(**over))
        assert REFEREE_CORE_KEYS <= set(v)             # verdict + narrative + metrics
        assert v["verdict"] in REFEREE_VERDICTS        # referee call words
        assert isinstance(v["narrative"], str) and v["narrative"].strip()
        assert isinstance(v["metrics"], dict) and v["metrics"]
    # The module's exported vocabulary is exactly the referee's.
    assert set(VERDICTS) == REFEREE_VERDICTS


def test_every_metric_kept_under_the_verdict():
    row = _row()
    v = analyze_walkforward(row)
    m = v["metrics"]
    # No metric is dropped — the numbers are still all there, now with a verdict.
    for k in ("avg_test_sharpe", "avg_train_sharpe", "overfit_drop",
              "avg_test_return_pct", "win_rate_windows_pct", "num_windows"):
        assert k in m


# --------------------------------------------------------------------------
# Wiring: response model carries the verdict end to end
# --------------------------------------------------------------------------
def test_verdict_in_response_schema():
    from services.api.routers.walkforwards import WalkforwardDetail
    assert "analysis" in WalkforwardDetail.model_json_schema()["properties"]


def test_row_to_detail_attaches_verdict():
    from services.api.routers.walkforwards import _row_to_detail
    row = {
        "id": uuid4(),
        "strategy_name": "SPY RSI MR",
        "symbols": ["SPY@ALPACA"],
        "bar_resolution": "1d",
        "starting_cash": 10000,
        "fee_rate_bps": 10,
        "slippage_bps": 5,
        "param_grid": {"rsi_period": [14, 21]},
        "train_bars": 500,
        "test_bars": 150,
        "num_windows": 6,
        "selection_metric": "sharpe",
        "status": "completed",
        "created_at": datetime(2026, 6, 28, tzinfo=timezone.utc),
        "started_at": None,
        "completed_at": None,
        "duration_seconds": None,
        "error_message": None,
        "total_combos": 4,
        "total_backtests_run": 24,
        "windows_result": [],
        "avg_train_sharpe": 1.6,
        "avg_test_sharpe": -0.4,      # fails OOS
        "avg_test_return_pct": -2.0,
        "overfit_drop": 2.0,
        "win_rate_windows_pct": 33.0,
    }
    detail = _row_to_detail(row)
    assert detail.analysis is not None
    assert detail.analysis["verdict"] == "REJECT"
    assert detail.analysis["next_action"]["action"] == "edit_strategy"
    assert detail.analysis["findings"]
