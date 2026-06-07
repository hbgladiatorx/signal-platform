"""Tests for the deterministic node-graph → Strategy source compiler.

These guard the regression where a long/short RSI mean-reversion graph compiled
to impossible conditions ("RSI < 30 and RSI > 70"), so every backtest returned
0 trades. The engine is long-only, so only the long leg must be compiled.
"""

from __future__ import annotations

from packages.strategy.graph_compiler import compile_graph_to_source


def _long_short_rsi_graph() -> dict:
    """RSI mean reversion with BOTH a long and a short leg, as the planner emits.

    oversold (RSI<30)  → long entry  + short exit
    overbought (RSI>70) → long exit  + short entry
    """
    return {
        "nodes": [
            {"id": "price-1", "type": "price",
             "data": {"symbol": "BTC-USDT@BINANCEUS", "timeframe": "1m"}},
            {"id": "rsi-1", "type": "rsi", "data": {"period": 14}},
            {"id": "oversold-1", "type": "comparator", "label": "RSI < 30",
             "data": {"op": "<", "value": 30}},
            {"id": "overbought-1", "type": "comparator", "label": "RSI > 70",
             "data": {"op": ">", "value": 70}},
            {"id": "long-entry-1", "type": "entry", "label": "Entry LONG",
             "data": {"direction": "LONG"}},
            {"id": "long-exit-1", "type": "exit", "label": "Exit LONG", "data": {}},
            {"id": "short-entry-1", "type": "entry", "label": "Entry SHORT",
             "data": {"direction": "SHORT"}},
            {"id": "short-exit-1", "type": "exit", "label": "Exit SHORT", "data": {}},
        ],
        "edges": [
            {"source": "price-1", "target": "rsi-1"},
            {"source": "rsi-1", "target": "oversold-1"},
            {"source": "rsi-1", "target": "overbought-1"},
            {"source": "oversold-1", "target": "long-entry-1"},
            {"source": "overbought-1", "target": "long-exit-1"},
            {"source": "overbought-1", "target": "short-entry-1"},
            {"source": "oversold-1", "target": "short-exit-1"},
        ],
    }


def test_long_short_graph_compiles_long_only_without_contradiction():
    res = compile_graph_to_source(
        name="BTC RSI Mean Reversion", asset_class="crypto",
        graph=_long_short_rsi_graph(),
    )
    assert res.ok, res.reason
    src = res.source_code
    assert src is not None

    # The long entry fires when oversold (RSI < 30), the long exit when
    # overbought (RSI > 70). Neither line may AND the two opposing comparators.
    assert "if position == 0 and (rsi_14 < self.params.entry_threshold)" in src
    assert "if position > 0 and (rsi_14 > self.params.exit_threshold)" in src

    # No impossible "RSI < X and RSI > Y" (or vice-versa) on one line.
    for line in src.splitlines():
        if "rsi_14 <" in line and "rsi_14 >" in line:
            raise AssertionError(f"contradictory condition compiled: {line!r}")

    # Short legs were dropped and the user is told so.
    assert any("long-only" in n for n in res.notes)

    # The compiled source is valid, importable Python.
    compile(src, "<compiled>", "exec")


def test_position_size_node_sizes_from_equity_not_001_units():
    """A 'Position Size 2%' node must size from account equity, not 0.01 units.

    Regression: the compiler hardcoded 0.01 base units, so a $25k account took
    ~$5 positions and every backtest returned ~0%. It must instead read the
    positionSize node and size qty = (pct/100) * ctx.cash / price.
    """
    graph = _long_short_rsi_graph()
    graph["nodes"].append({
        "id": "size-1", "type": "positionSize", "label": "Position Size 2%",
        "data": {"type": "percent_account", "value": 2},
    })
    graph["edges"].append({"source": "size-1", "target": "long-entry-1"})

    res = compile_graph_to_source(name="Sized", asset_class="equity", graph=graph)
    assert res.ok, res.reason
    src = res.source_code
    assert "position_pct: float" in src
    assert "default=2" in src
    assert "ctx.cash / price" in src
    assert "Decimal(str(self.params.position_pct))" in src
    # the broken hardcoded sizing must be gone
    assert "position_size" not in src
    assert "Decimal(str(self.params.position_size))" not in src
    compile(src, "<compiled>", "exec")


def test_fixed_cash_sizing():
    graph = _long_short_rsi_graph()
    graph["nodes"].append({
        "id": "size-1", "type": "positionSize", "label": "Position Size $5000",
        "data": {"type": "fixed_cash", "value": 5000},
    })
    graph["edges"].append({"source": "size-1", "target": "long-entry-1"})
    res = compile_graph_to_source(name="Sized", asset_class="equity", graph=graph)
    assert res.ok, res.reason
    src = res.source_code
    assert "position_cash: float" in src
    assert "default=5000" in src
    assert "Decimal(str(self.params.position_cash)) / price" in src
    compile(src, "<compiled>", "exec")


def test_no_size_node_defaults_to_percent_of_account():
    """No positionSize node → default to a percent of equity, never 0.01 units."""
    graph = {
        "nodes": [
            {"id": "price-1", "type": "price",
             "data": {"symbol": "SPY@ALPACA", "timeframe": "1h"}},
            {"id": "rsi-1", "type": "rsi", "data": {"period": 14}},
            {"id": "cmp-1", "type": "comparator", "label": "RSI < 30",
             "data": {"op": "<", "value": 30}},
            {"id": "entry-1", "type": "entry", "label": "Entry LONG",
             "data": {"direction": "LONG"}},
        ],
        "edges": [
            {"source": "price-1", "target": "rsi-1"},
            {"source": "rsi-1", "target": "cmp-1"},
            {"source": "cmp-1", "target": "entry-1"},
        ],
    }
    res = compile_graph_to_source(name="Default", asset_class="equity", graph=graph)
    assert res.ok, res.reason
    assert "position_pct: float" in res.source_code
    assert "ctx.cash / price" in res.source_code


def test_pure_long_graph_still_compiles():
    """A plain single-leg long graph (no short nodes) is unaffected."""
    graph = {
        "nodes": [
            {"id": "price-1", "type": "price",
             "data": {"symbol": "SPY@ALPACA", "timeframe": "1h"}},
            {"id": "rsi-1", "type": "rsi", "data": {"period": 14}},
            {"id": "cmp-1", "type": "comparator", "label": "RSI < 30",
             "data": {"op": "<", "value": 30}},
            {"id": "entry-1", "type": "entry", "label": "Entry LONG",
             "data": {"direction": "LONG"}},
        ],
        "edges": [
            {"source": "price-1", "target": "rsi-1"},
            {"source": "rsi-1", "target": "cmp-1"},
            {"source": "cmp-1", "target": "entry-1"},
        ],
    }
    res = compile_graph_to_source(name="SPY RSI", asset_class="equity", graph=graph)
    assert res.ok, res.reason
    assert res.notes == []  # nothing dropped
    assert "rsi_14 < self.params.entry_threshold" in res.source_code


def test_short_only_graph_falls_back():
    """A long-only engine can't represent a short-only strategy → ok=False."""
    graph = {
        "nodes": [
            {"id": "price-1", "type": "price",
             "data": {"symbol": "SPY@ALPACA", "timeframe": "1h"}},
            {"id": "rsi-1", "type": "rsi", "data": {"period": 14}},
            {"id": "cmp-1", "type": "comparator", "label": "RSI > 70",
             "data": {"op": ">", "value": 70}},
            {"id": "entry-1", "type": "entry", "label": "Entry SHORT",
             "data": {"direction": "SHORT"}},
        ],
        "edges": [
            {"source": "price-1", "target": "rsi-1"},
            {"source": "rsi-1", "target": "cmp-1"},
            {"source": "cmp-1", "target": "entry-1"},
        ],
    }
    res = compile_graph_to_source(name="SPY Short", asset_class="equity", graph=graph)
    assert not res.ok
