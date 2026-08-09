"""Tests for risk-language disambiguation.

Defect being guarded: a phrase like "risk 2% per trade" is ambiguous between a
2% position size and a 2% stop-loss (opposite economics). Both build paths used
to resolve it silently — and could resolve it DIFFERENTLY. These tests pin down:

  * the deterministic detector classifies ambiguous vs unambiguous risk language;
  * the graph compiler emits a machine-readable `risk_flag` and applies the
    documented default (a stop-loss) for the ambiguous case, and stays silent on
    unambiguous cases (no regressions);
  * the LLM-translator path attaches the SAME flag from the SAME detector, so the
    two paths can never disagree.
"""
from __future__ import annotations

import sys
import types

from packages.strategy.graph_compiler import compile_graph_to_source
from packages.strategy.risk_language import (
    DEFAULT_INTERPRETATION,
    detect_risk_ambiguity,
)


# --------------------------------------------------------------------------
# Detector
# --------------------------------------------------------------------------
def test_bare_risk_phrase_is_ambiguous():
    flag = detect_risk_ambiguity("Buy SPY when RSI < 30, risk 2% per trade")
    assert flag is not None
    assert flag.ambiguous is True
    assert flag.value == 2.0
    assert flag.applied_interpretation == DEFAULT_INTERPRETATION == "stop_loss"
    assert flag.alternative_interpretation == "position_size"
    assert flag.needs_confirmation is True
    # The message names BOTH meanings and the applied default, in plain English.
    assert "stop-loss" in flag.message
    assert "position size" in flag.message


def test_risk_word_order_variant_is_ambiguous():
    assert detect_risk_ambiguity("2% risk per position") is not None


def test_explicit_stop_is_not_ambiguous():
    assert detect_risk_ambiguity("Buy SPY when RSI < 30, 2% stop") is None
    assert detect_risk_ambiguity("stop loss 2%") is None
    assert detect_risk_ambiguity("use a 3% stop-loss") is None


def test_explicit_size_is_not_ambiguous():
    assert detect_risk_ambiguity("position size 2%") is None
    assert detect_risk_ambiguity("size 2% of account per trade") is None
    assert detect_risk_ambiguity("allocate 5% of equity") is None


def test_no_risk_language_is_not_ambiguous():
    assert detect_risk_ambiguity("Buy SPY when RSI drops below 30, exit above 50") is None
    assert detect_risk_ambiguity("") is None
    assert detect_risk_ambiguity(None) is None


# --------------------------------------------------------------------------
# Graph compiler
# --------------------------------------------------------------------------
def _rsi_long_graph() -> dict:
    """A minimal compilable long-only RSI graph (no risk node)."""
    return {
        "nodes": [
            {"id": "price-1", "type": "price",
             "data": {"symbol": "SPY@ALPACA", "timeframe": "1d"}},
            {"id": "rsi-1", "type": "rsi", "data": {"period": 14}},
            {"id": "os-1", "type": "comparator", "label": "RSI < 30",
             "data": {"op": "<", "value": 30}},
            {"id": "ob-1", "type": "comparator", "label": "RSI > 50",
             "data": {"op": ">", "value": 50}},
            {"id": "entry-1", "type": "entry", "label": "Entry LONG",
             "data": {"direction": "LONG"}},
            {"id": "exit-1", "type": "exit", "label": "Exit", "data": {}},
        ],
        "edges": [
            {"source": "price-1", "target": "rsi-1"},
            {"source": "rsi-1", "target": "os-1"},
            {"source": "rsi-1", "target": "ob-1"},
            {"source": "os-1", "target": "entry-1"},
            {"source": "ob-1", "target": "exit-1"},
        ],
    }


def test_ambiguous_description_flags_and_applies_stop_default():
    graph = _rsi_long_graph()
    res = compile_graph_to_source(
        name="SPY RSI", asset_class="equity", graph=graph,
        description="Buy SPY when RSI < 30, risk 2% per trade",
    )
    assert res.ok, res.reason
    assert res.risk_flag is not None
    assert res.risk_flag["kind"] == "risk_ambiguity"
    assert res.risk_flag["applied_interpretation"] == "stop_loss"
    assert res.risk_flag["value"] == 2.0
    # Documented default applied: a 2% stop-loss is in the emitted source...
    assert "stop_loss_percent" in res.source_code
    assert "default=2.0" in res.source_code
    # ...and sizing was NOT set to 2% (that would be the OTHER interpretation).
    assert "default=95.0" in res.source_code


def test_planner_misread_positionsize_is_corrected_to_stop():
    """If the planner silently turned "risk 2%" into a positionSize node, the
    compiler undoes it so the strategy matches the stop-loss flag."""
    graph = _rsi_long_graph()
    graph["nodes"].append(
        {"id": "size-1", "type": "positionSize",
         "data": {"type": "percent_account", "value": 2}}
    )
    res = compile_graph_to_source(
        name="SPY RSI", asset_class="equity", graph=graph,
        description="risk 2% per trade",
    )
    assert res.ok, res.reason
    assert res.risk_flag is not None
    # The 2% positionSize was reverted to the 95% default and a 2% stop applied.
    assert "default=95.0" in res.source_code
    assert "stop_loss_percent" in res.source_code
    assert "default=2.0" in res.source_code


def test_explicit_size_language_is_preserved_no_flag():
    """An explicit positionSize node + explicit size language: no flag, honored."""
    graph = _rsi_long_graph()
    graph["nodes"].append(
        {"id": "size-1", "type": "positionSize",
         "data": {"type": "percent_account", "value": 2}}
    )
    res = compile_graph_to_source(
        name="SPY RSI", asset_class="equity", graph=graph,
        description="size 2% of account per trade",
    )
    assert res.ok, res.reason
    assert res.risk_flag is None
    assert "default=2.0" in res.source_code  # 2% sizing honored


def test_explicit_stop_node_no_flag():
    graph = _rsi_long_graph()
    graph["nodes"].append(
        {"id": "stop-1", "type": "stopLoss", "data": {"type": "percent", "value": 2}}
    )
    res = compile_graph_to_source(
        name="SPY RSI", asset_class="equity", graph=graph,
        description="Buy SPY when RSI < 30 with a 2% stop",
    )
    assert res.ok, res.reason
    assert res.risk_flag is None
    assert "stop_loss_percent" in res.source_code


def test_no_description_no_flag_backcompat():
    """Callers that don't pass a description behave exactly as before."""
    res = compile_graph_to_source(
        name="SPY RSI", asset_class="equity", graph=_rsi_long_graph()
    )
    assert res.ok, res.reason
    assert res.risk_flag is None


# --------------------------------------------------------------------------
# Cross-path parity: deterministic compiler and LLM translator agree
# --------------------------------------------------------------------------
def test_compiler_flag_equals_shared_detector():
    text = "risk 2% per trade"
    res = compile_graph_to_source(
        name="X", asset_class="equity", graph=_rsi_long_graph(), description=text
    )
    assert res.risk_flag == detect_risk_ambiguity(text).to_dict()


def test_translator_attaches_same_flag(monkeypatch):
    """Drive translate_nl_to_strategy with a fake Anthropic client and assert it
    attaches the IDENTICAL flag the compiler would — proving the two build paths
    cannot disagree on the ambiguous case."""
    from packages.strategy import llm_translator

    tool_block = types.SimpleNamespace(
        type="tool_use",
        name="emit_strategy_code",
        input={
            "source_code": "# strategy",
            "class_name": "Foo",
            "params_class_name": "FooParams",
            "suggested_strategy_name": "Foo",
            "explanation": "ok",
        },
    )
    response = types.SimpleNamespace(
        content=[tool_block],
        usage=types.SimpleNamespace(input_tokens=1, output_tokens=1),
    )

    class _Msgs:
        def create(self, **_kw):
            return response

    class _Client:
        def __init__(self, **_kw):
            self.messages = _Msgs()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Client
    fake.APIError = Exception
    fake.APITimeoutError = Exception
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    text = "risk 2% per trade"
    result = llm_translator.translate_nl_to_strategy(nl_description=text)
    assert result.ok, result.error
    assert result.risk_flag == detect_risk_ambiguity(text).to_dict()


def test_translator_no_flag_on_unambiguous(monkeypatch):
    from packages.strategy import llm_translator

    tool_block = types.SimpleNamespace(
        type="tool_use", name="emit_strategy_code",
        input={"source_code": "# s", "class_name": "F", "params_class_name": "FP"},
    )
    response = types.SimpleNamespace(
        content=[tool_block],
        usage=types.SimpleNamespace(input_tokens=1, output_tokens=1),
    )

    class _Msgs:
        def create(self, **_kw):
            return response

    class _Client:
        def __init__(self, **_kw):
            self.messages = _Msgs()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Client
    fake.APIError = Exception
    fake.APITimeoutError = Exception
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = llm_translator.translate_nl_to_strategy(nl_description="2% stop loss")
    assert result.ok
    assert result.risk_flag is None
