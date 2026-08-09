"""The system must never advise, offer, or accept a multi-symbol run that then
crashes the single-symbol strategy contract.

Resolution chosen: Option B — refuse multi-symbol cleanly and stop advising /
offering it. These tests pin down all four guarantees:

  * a genuine SINGLE-symbol strategy still works exactly as before;
  * the previously-crashing multi-symbol case is refused with a clear, caught
    message (compiled on_init backstop; copilot resolve; API accept-time block);
  * the validation "add symbols" advice no longer points at a crashing action.
"""
from __future__ import annotations

import asyncio
import types
from uuid import uuid4

import pytest

from packages.strategy.graph_compiler import compile_graph_to_source


def _rsi_long_graph() -> dict:
    """A minimal compilable long-only RSI graph (single price node)."""
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


def _load_compiled():
    res = compile_graph_to_source(name="SPY RSI", asset_class="equity",
                                  graph=_rsi_long_graph())
    assert res.ok, res.reason
    ns: dict = {}
    exec(compile(res.source_code, "<compiled>", "exec"), ns)
    return ns[res.class_name]


# --------------------------------------------------------------------------
# The compiled-strategy contract (backstop)
# --------------------------------------------------------------------------
def test_single_symbol_strategy_still_works():
    cls = _load_compiled()
    strat = cls(symbols=["SPY@ALPACA"], params=cls.PARAMS_MODEL())
    strat.on_init()  # must NOT raise
    assert strat.symbol == "SPY@ALPACA"


def test_multi_symbol_refused_gracefully_with_clear_message():
    cls = _load_compiled()
    strat = cls(symbols=["SPY@ALPACA", "AAPL@ALPACA"], params=cls.PARAMS_MODEL())
    with pytest.raises(ValueError) as ei:
        strat.on_init()
    msg = str(ei.value).lower()
    # Clear and explained — names the limit and that multi-symbol isn't supported.
    assert "single symbol" in msg
    assert "multi-symbol" in msg and "supported yet" in msg
    # Echoes what was given so the user understands the refusal.
    assert "aapl@alpaca" in msg


# --------------------------------------------------------------------------
# The copilot run entry no longer OFFERS/ACCEPTS multi-symbol / UNIVERSE
# --------------------------------------------------------------------------
def test_copilot_resolve_refuses_universe():
    from packages.copilot import tools
    from packages.copilot.tools import ToolError, SINGLE_SYMBOL_MSG
    with pytest.raises(ToolError) as ei:
        asyncio.run(tools._resolve_symbols(None, uuid4(), "S", ["UNIVERSE"]))
    assert str(ei.value) == SINGLE_SYMBOL_MSG


def test_copilot_resolve_refuses_multi_symbol(monkeypatch):
    from packages.copilot import tools
    from packages.copilot.tools import ToolError, SINGLE_SYMBOL_MSG

    async def fake_filter(_session, cands):
        return list(cands)  # pretend all requested symbols exist
    monkeypatch.setattr(tools, "_filter_known_symbols", fake_filter)

    with pytest.raises(ToolError) as ei:
        asyncio.run(tools._resolve_symbols(None, uuid4(), "S", ["SPY", "AAPL"]))
    assert str(ei.value) == SINGLE_SYMBOL_MSG


def test_copilot_resolve_allows_single_symbol(monkeypatch):
    from packages.copilot import tools

    async def fake_filter(_session, cands):
        return list(cands)
    monkeypatch.setattr(tools, "_filter_known_symbols", fake_filter)

    out = asyncio.run(tools._resolve_symbols(None, uuid4(), "S", ["SPY"]))
    assert out == ["SPY"]


def test_universe_symbols_list_removed():
    """The 50-name UNIVERSE expansion is gone — it can no longer be offered."""
    from packages.copilot import tools
    assert not hasattr(tools, "UNIVERSE_SYMBOLS")


# --------------------------------------------------------------------------
# The HTTP backtest-create endpoint refuses multi-symbol at acceptance
# --------------------------------------------------------------------------
def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.api.deps import get_current_user_record, get_db_session
    from services.api.routers import backtests as bt

    app = FastAPI()
    app.include_router(bt.router)
    app.dependency_overrides[get_current_user_record] = lambda: types.SimpleNamespace(
        id=uuid4(), org_id=None, email="t@t", role="user"
    )
    # The multi-symbol refusal fires before any DB work, so a dummy session that
    # is never touched is enough (avoids needing a live DATABASE_URL).
    app.dependency_overrides[get_db_session] = lambda: types.SimpleNamespace()
    return TestClient(app)


def test_api_refuses_multi_symbol_backtest():
    body = {
        "strategy_name": "SPY RSI",
        "symbols": ["SPY@ALPACA", "AAPL@ALPACA"],
        "bar_resolution": "1d",
    }
    r = _client().post("/backtests", json=body)
    assert r.status_code == 422, r.text
    msg = r.json()["detail"]["msg"].lower()
    assert "one symbol" in msg and "aren't supported yet" in msg
    # Refused at acceptance — before any strategy/DB work — never queued.


# --------------------------------------------------------------------------
# The "add symbols" advice no longer points at a crashing action
# --------------------------------------------------------------------------
def test_low_sample_advice_no_longer_suggests_adding_symbols():
    from packages.analysis.backtest_analysis import analyze_backtest
    out = analyze_backtest(
        {"profit_factor": 1.2, "sharpe_ratio": 0.8, "win_rate_pct": 55,
         "avg_winner_pct": 2.0, "avg_loser_pct": -1.5, "num_closed_trades": 5,
         "total_return_pct": 3.0},
        attribution=None, ml_model=None,
    )
    low = next(f for f in out["findings"] if f["id"] == "low-sample")
    s = low["suggestion"].lower()
    assert "more symbols" not in s and "add symbol" not in s
    assert "date range" in s or "timeframe" in s


def test_copilot_prompt_no_longer_advises_adding_symbols():
    from packages.copilot import prompt
    text = open(prompt.__file__).read().lower()
    # The old "propose the fix (widen the date range, add symbols)" advice is gone.
    assert "date range, add symbols" not in text
    # ...replaced with single-symbol-aware guidance.
    assert "single symbol" in text
