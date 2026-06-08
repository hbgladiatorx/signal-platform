"""Phase 3 ML: feature/label store extraction + signal-edge model.

Two layers are tested separately:

  * build_dataset() — run a real backtest with signal-emitting strategies and
    check the feature matrix shape, labels, and the leak-free value join
    (a feature carries the *decision-bar* reading, not the fill price).
  * train_signal_edge_model() — fit on hand-built separable matrices so the
    learned weights / accuracy are deterministic and assertable, plus the
    degenerate guards (too few samples, single class) and JSON serialization.
"""
from __future__ import annotations

import json
from decimal import Decimal

import numpy as np
import pandas as pd
from pydantic import BaseModel

from packages.backtest.analytics import compute_analytics
from packages.backtest.engine import run_backtest
from packages.backtest.types import BacktestConfig
from datetime import datetime, timezone

from packages.ml import (
    FeatureSample,
    TrainingDataset,
    build_dataset,
    extract_samples,
    model_to_dict,
    samples_to_dataset,
    train_signal_edge_model,
)
from packages.ml.model import MIN_SAMPLES_TO_FIT
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


# ============================================================
# Dataset builder (from a real backtest)
# ============================================================
class _TaggedTwoSymbol(Strategy):
    """Buy both symbols on bar 0 tagged 'trend' (after a blocked 'cooldown'
    filter), sell both on bar 2 tagged 'tp'."""

    class PARAMS_MODEL(BaseModel):  # noqa: D106
        pass

    def on_bar(self, ctx: BarContext) -> None:
        if ctx.bar_count == 0:
            for s in self.symbols:
                ctx.signal("cooldown", passed=False, symbol=s)
                ctx.signal("trend", value=ctx.close(s), symbol=s)
                ctx.submit_buy_market(s, 1)
        elif ctx.bar_count == 2:
            for s in self.symbols:
                ctx.signal("tp", symbol=s)
                ctx.submit_sell_market(s, 1)


def _bars(opens: list[int]) -> pd.DataFrame:
    idx = pd.to_datetime([f"2026-01-0{i + 1}" for i in range(len(opens))], utc=True)
    return pd.DataFrame(
        {"open": opens, "high": opens, "low": opens, "close": opens,
         "volume": [10] * len(opens)},
        index=idx,
    )


def _run_two_symbol():
    win, lose = "WIN@X", "LOSE@X"
    bars = {
        win: _bars([100, 110, 120, 130]),   # +20
        lose: _bars([100, 95, 90, 85]),     # -10
    }
    cfg = BacktestConfig(starting_cash=Decimal("10000"), fee_rate_bps=0, slippage_bps=0)
    strat = _TaggedTwoSymbol(symbols=[win, lose], params=_TaggedTwoSymbol.PARAMS_MODEL())
    return win, lose, run_backtest(strat, bars, cfg)


def test_build_dataset_shape_and_labels():
    win, lose, result = _run_two_symbol()
    analytics = compute_analytics(result)
    ds = build_dataset(result, analytics)

    # Two closed trips -> two rows. Vocabulary excludes 'cooldown' (only ever a
    # blocking filter, never passed -> can't be active at entry). Sorted.
    assert ds.n_samples == 2
    assert ds.signal_names == ["tp", "trend"]
    # Per signal: active + value columns, then the count feature.
    assert ds.feature_names[-1] == "n_active_signals"
    assert ds.n_features == len(ds.signal_names) * 2 + 1

    # Labels: WIN trip profitable (1), LOSE trip not (0).
    by_label = dict(zip(ds.row_symbols, ds.y_class.tolist(), strict=True))
    assert by_label[win] == 1
    assert by_label[lose] == 0
    by_pnl = dict(zip(ds.row_symbols, ds.y_pnl.tolist(), strict=True))
    assert by_pnl[win] == 20.0
    assert by_pnl[lose] == -10.0


def test_build_dataset_value_join_uses_decision_bar_not_fill():
    """The 'trend' value feature must be the close at the *decision* bar (100),
    not the entry fill price (110 for WIN / 95 for LOSE)."""
    win, lose, result = _run_two_symbol()
    analytics = compute_analytics(result)
    ds = build_dataset(result, analytics)

    trend_active = ds.feature_names.index("sig::trend::active")
    trend_value = ds.feature_names.index("sig::trend::value")
    for row, sym in zip(ds.X, ds.row_symbols, strict=True):
        assert row[trend_active] == 1.0          # trend tagged every entry
        assert row[trend_value] == 100.0         # decision-bar close, not fill
        # 'tp' is an exit tag -> never active on an entry row.
        assert row[ds.feature_names.index("sig::tp::active")] == 0.0


def test_build_dataset_empty_when_no_signals():
    class _NoSignals(Strategy):
        class PARAMS_MODEL(BaseModel):  # noqa: D106
            pass

        def on_bar(self, ctx: BarContext) -> None:
            if ctx.bar_count == 0:
                ctx.submit_buy_market(self.symbols[0], 1)

    sym = "BTC-USDT@BINANCEUS"
    cfg = BacktestConfig(starting_cash=Decimal("10000"), fee_rate_bps=0, slippage_bps=0)
    strat = _NoSignals(symbols=[sym], params=_NoSignals.PARAMS_MODEL())
    result = run_backtest(strat, {sym: _bars([100, 110, 120])}, cfg)

    ds = build_dataset(result, compute_analytics(result))
    assert ds.n_samples == 0
    assert ds.signal_names == []


# ============================================================
# Model fitting (hand-built separable data)
# ============================================================
def _separable_dataset(n_per_class: int = 10) -> TrainingDataset:
    """Two signals: 'good' rows are all profitable, 'bad' rows all losing.

    Columns: sig::bad::active, sig::bad::value, sig::good::active,
    sig::good::value, n_active_signals (signal_names sorted: bad, good).
    """
    feature_names = [
        "sig::bad::active", "sig::bad::value",
        "sig::good::active", "sig::good::value",
        "n_active_signals",
    ]
    rows: list[list[float]] = []
    y: list[int] = []
    syms: list[str] = []
    for i in range(n_per_class):
        rows.append([0.0, 0.0, 1.0, float(1 + i), 1.0])  # good -> win
        y.append(1)
        syms.append("G")
    for i in range(n_per_class):
        rows.append([1.0, float(1 + i), 0.0, 0.0, 1.0])  # bad -> loss
        y.append(0)
        syms.append("B")
    return TrainingDataset(
        feature_names=feature_names,
        X=np.asarray(rows, dtype=float),
        y_class=np.asarray(y, dtype=int),
        y_pnl=np.asarray([1.0 if v else -1.0 for v in y], dtype=float),
        row_symbols=syms,
        signal_names=["bad", "good"],
    )


def test_model_learns_separable_signal():
    ds = _separable_dataset(10)
    model = train_signal_edge_model(ds)

    assert model.fitted is True
    assert model.reason is None
    assert model.train_accuracy == 1.0          # perfectly separable
    assert model.base_profit_rate == 0.5

    # 'good' should carry a positive active-weight, 'bad' negative.
    weights = {w.feature: w.weight for w in model.feature_weights}
    assert weights["sig::good::active"] > 0
    assert weights["sig::bad::active"] < 0

    # Per-signal edges: good above base, bad below.
    edges = {e.name: e for e in model.signal_edges}
    assert edges["good"].empirical_profit_rate == 1.0
    assert edges["good"].lift_vs_base_pp > 0
    assert edges["bad"].empirical_profit_rate == 0.0
    assert edges["bad"].lift_vs_base_pp < 0
    # Ordered by lift desc -> good first.
    assert model.signal_edges[0].name == "good"


def test_model_is_deterministic():
    ds = _separable_dataset(12)
    a = model_to_dict(train_signal_edge_model(ds))
    b = model_to_dict(train_signal_edge_model(ds))
    assert a == b


def test_model_unfitted_when_too_few_samples():
    ds = _separable_dataset(2)  # 4 rows < MIN_SAMPLES_TO_FIT
    assert ds.n_samples < MIN_SAMPLES_TO_FIT
    model = train_signal_edge_model(ds)
    assert model.fitted is False
    assert model.reason and "need" in model.reason
    assert model.train_accuracy is None
    # Empirical edges still computed (need no model).
    assert {e.name for e in model.signal_edges} == {"good", "bad"}


def test_model_unfitted_when_single_class():
    ds = _separable_dataset(10)
    # Force all-profitable.
    ds_one = TrainingDataset(
        feature_names=ds.feature_names,
        X=ds.X,
        y_class=np.ones_like(ds.y_class),
        y_pnl=np.abs(ds.y_pnl),
        row_symbols=ds.row_symbols,
        signal_names=ds.signal_names,
    )
    model = train_signal_edge_model(ds_one)
    assert model.fitted is False
    assert model.reason and "single-class" in model.reason


def test_model_to_dict_is_json_safe():
    model = train_signal_edge_model(_separable_dataset(10))
    d = model_to_dict(model)
    assert json.loads(json.dumps(d)) == d
    assert d["fitted"] is True
    assert d["count_feature"] == "n_active_signals"
    assert isinstance(d["signal_edges"], list)
    assert d["hyperparams"]["iterations"] > 0


# ============================================================
# Cross-backtest store: extract_samples + samples_to_dataset
# ============================================================
def test_extract_samples_from_backtest():
    win, lose, result = _run_two_symbol()
    samples = extract_samples(result, compute_analytics(result))

    assert len(samples) == 2
    by_sym = {s.symbol: s for s in samples}
    assert by_sym[win].profitable is True
    assert by_sym[win].net_pnl == 20.0
    assert by_sym[lose].profitable is False
    # Only the entry signal 'trend' is active (with its decision-bar value 100);
    # 'tp' is an exit tag and 'cooldown' never passed.
    for s in samples:
        assert s.signal_values == {"trend": 100.0}


def _mk(profitable: bool, signal_values: dict[str, float | None]) -> FeatureSample:
    return FeatureSample(
        symbol="X",
        entry_ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        profitable=profitable,
        net_pnl=1.0 if profitable else -1.0,
        signal_values=signal_values,
    )


def test_samples_to_dataset_unifies_heterogeneous_vocabularies():
    # Two runs with different signal sets: run A fired 'alpha', run B 'beta'.
    samples = [
        _mk(True, {"alpha": 1.0}),
        _mk(False, {"alpha": 2.0}),
        _mk(True, {"beta": 3.0}),
        _mk(False, {"beta": 4.0}),
    ]
    ds = samples_to_dataset(samples)

    assert ds.signal_names == ["alpha", "beta"]
    assert ds.n_samples == 4
    # alpha rows have beta inactive and vice versa.
    a_active = ds.feature_names.index("sig::alpha::active")
    b_active = ds.feature_names.index("sig::beta::active")
    assert ds.X[0, a_active] == 1.0 and ds.X[0, b_active] == 0.0
    assert ds.X[2, b_active] == 1.0 and ds.X[2, a_active] == 0.0
    # Value join carried through.
    b_value = ds.feature_names.index("sig::beta::value")
    assert ds.X[2, b_value] == 3.0


def test_samples_to_dataset_empty():
    ds = samples_to_dataset([])
    assert ds.n_samples == 0
    assert ds.signal_names == []


def test_aggregate_dataset_trains():
    # 20 separable samples across the unified vocabulary -> fits perfectly.
    samples = [_mk(True, {"good": float(1 + i)}) for i in range(10)]
    samples += [_mk(False, {"bad": float(1 + i)}) for i in range(10)]
    ds = samples_to_dataset(samples)
    model = train_signal_edge_model(ds)

    assert model.fitted is True
    assert model.train_accuracy == 1.0
    edges = {e.name: e for e in model.signal_edges}
    assert edges["good"].lift_vs_base_pp > 0
    assert edges["bad"].lift_vs_base_pp < 0


def test_extract_then_aggregate_preserves_labels():
    _, _, result = _run_two_symbol()
    samples = extract_samples(result, compute_analytics(result))
    ds = samples_to_dataset(samples)
    # One win, one loss -> base rate 0.5, labels preserved.
    assert sorted(ds.y_class.tolist()) == [0, 1]
    assert ds.base_profit_rate == 0.5
