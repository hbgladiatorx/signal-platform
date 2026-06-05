"""Deterministic backtest analysis engine: verdicts, breakeven math, and the
signal/symbol/ML findings derived from the structured inputs.
"""
from __future__ import annotations

from packages.analysis.backtest_analysis import analyze_backtest


def _finding_ids(analysis: dict) -> set[str]:
    return {f["id"] for f in analysis["findings"]}


def _severities(analysis: dict) -> list[str]:
    return [f["severity"] for f in analysis["findings"]]


def test_empty_backtest_is_inconclusive():
    a = analyze_backtest({"num_closed_trades": 0}, None, None)
    assert a["verdict"] == "inconclusive"
    assert a["score"] == 0
    assert "no-trades" in _finding_ids(a)


def test_strong_strategy_is_profitable():
    metrics = {
        "profit_factor": 2.1, "sharpe_ratio": 1.4, "sortino_ratio": 2.0,
        "win_rate_pct": 55, "avg_winner_pct": 3.0, "avg_loser_pct": -1.5,
        "max_drawdown_pct": -12, "total_return_pct": 40, "num_closed_trades": 120,
    }
    a = analyze_backtest(metrics, None, None)
    assert a["verdict"] == "profitable"
    assert a["score"] > 60
    assert "pf-strong" in _finding_ids(a)


def test_unprofitable_when_profit_factor_below_one():
    metrics = {
        "profit_factor": 0.8, "sharpe_ratio": -0.3, "win_rate_pct": 30,
        "avg_winner_pct": 1.0, "avg_loser_pct": -1.5,
        "max_drawdown_pct": -40, "total_return_pct": -15, "num_closed_trades": 90,
    }
    a = analyze_backtest(metrics, None, None)
    assert a["verdict"] == "unprofitable"
    assert "pf-weak" in _finding_ids(a)
    assert "winrate-below" in _finding_ids(a)


def test_breakeven_math():
    # payoff 2:1 -> breakeven win = 1/(1+2) = 33.3%
    metrics = {
        "profit_factor": 1.3, "sharpe_ratio": 0.8, "win_rate_pct": 40,
        "avg_winner_pct": 2.0, "avg_loser_pct": -1.0,
        "max_drawdown_pct": -10, "total_return_pct": 12, "num_closed_trades": 80,
    }
    a = analyze_backtest(metrics, None, None)
    assert abs(a["metrics"]["breakeven_win_pct"] - 33.33) < 0.1
    assert abs(a["metrics"]["payoff_ratio"] - 2.0) < 1e-9
    # expectancy = 0.4*2.0 - 0.6*1.0 = 0.2
    assert abs(a["metrics"]["expectancy_pct"] - 0.2) < 1e-9


def test_low_sample_downgrades_profitable_to_marginal():
    metrics = {
        "profit_factor": 2.0, "sharpe_ratio": 1.2, "win_rate_pct": 60,
        "avg_winner_pct": 2.0, "avg_loser_pct": -1.0,
        "max_drawdown_pct": -8, "total_return_pct": 25, "num_closed_trades": 9,
    }
    a = analyze_backtest(metrics, None, None)
    assert a["verdict"] == "marginal"
    assert "low-sample" in _finding_ids(a)


def test_dragging_signal_flagged_from_attribution():
    metrics = {
        "profit_factor": 1.1, "sharpe_ratio": 0.4, "win_rate_pct": 40,
        "avg_winner_pct": 2.0, "avg_loser_pct": -1.5,
        "max_drawdown_pct": -20, "total_return_pct": 5, "num_closed_trades": 60,
    }
    attribution = {
        "num_closed_trades": 60, "untagged_trades": 0,
        "by_signal": [
            {"name": "good_sig", "num_trades": 40, "win_rate_pct": 50,
             "net_pnl": "1500", "pct_of_total_net_pnl": 80, "block_rate_pct": 50},
            {"name": "bad_sig", "num_trades": 20, "win_rate_pct": 20,
             "net_pnl": "-600", "pct_of_total_net_pnl": -30, "block_rate_pct": 50},
        ],
        "by_symbol": [
            {"symbol": "AAA", "num_trades": 30, "win_rate_pct": 55,
             "net_pnl": "1800", "pct_of_total_net_pnl": 90},
            {"symbol": "BBB", "num_trades": 30, "win_rate_pct": 30,
             "net_pnl": "-300", "pct_of_total_net_pnl": -15},
        ],
    }
    a = analyze_backtest(metrics, attribution, None)
    ids = _finding_ids(a)
    assert "sig-drag-bad_sig" in ids
    assert "sig-driver-good_sig" in ids
    # BBB is the worst (lossy) symbol
    assert "sym-worst-BBB" in ids


def test_ml_edges_surface_predictive_signals():
    metrics = {
        "profit_factor": 1.2, "sharpe_ratio": 0.6, "win_rate_pct": 42,
        "avg_winner_pct": 2.0, "avg_loser_pct": -1.3,
        "max_drawdown_pct": -15, "total_return_pct": 10, "num_closed_trades": 70,
    }
    ml_model = {
        "fitted": True, "base_profit_rate": 0.40,
        "signal_edges": [
            {"name": "edge_sig", "num_trades": 40, "empirical_profit_rate": 0.55,
             "mean_predicted_prob": 0.52, "lift_vs_base_pp": 12},
            {"name": "drag_sig", "num_trades": 30, "empirical_profit_rate": 0.28,
             "mean_predicted_prob": 0.27, "lift_vs_base_pp": -13},
        ],
    }
    a = analyze_backtest(metrics, None, ml_model)
    ids = _finding_ids(a)
    assert "ml-edge-edge_sig" in ids
    assert "ml-drag-drag_sig" in ids


def test_findings_sorted_worst_first():
    metrics = {
        "profit_factor": 1.1, "sharpe_ratio": 0.4, "win_rate_pct": 40,
        "avg_winner_pct": 2.0, "avg_loser_pct": -1.5,
        "max_drawdown_pct": -20, "total_return_pct": 5, "num_closed_trades": 60,
    }
    a = analyze_backtest(metrics, None, None)
    sevs = _severities(a)
    rank = {"bad": 0, "warn": 1, "good": 2, "info": 3}
    assert sevs == sorted(sevs, key=lambda s: rank[s])
