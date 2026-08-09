"""The graph the user wired is the SOURCE OF TRUTH for the run.

These tests pin the seam fixed here:

  * the run's symbol comes from the graph's data node, not a default or the
    stale last-backtest symbol (graph says X -> run executes on X);
  * a run request that DISAGREES with the graph is rejected, never silently
    honored (copilot path and the HTTP accept-time path);
  * an agreeing request (including a bare ticker vs the graph's canonical
    symbol) is honored unchanged;
  * the build-time assumptions travel with the strategy and are surfaced on the
    run result instead of dying at the build boundary.
"""
from __future__ import annotations

import asyncio
import types
from uuid import uuid4

import pytest

from packages.strategy.graph_intent import graph_bar_resolution, graph_symbol


# --------------------------------------------------------------------------
# graph_intent: the single extractor both run paths read intent through
# --------------------------------------------------------------------------
def _graph(symbol="SPY@ALPACA", timeframe="1d"):
    return {"nodes": [
        {"id": "price-1", "type": "price",
         "data": {"symbol": symbol, "timeframe": timeframe}},
        {"id": "rsi-1", "type": "rsi", "data": {"period": 14}},
    ]}


def test_graph_symbol_and_timeframe_extracted():
    g = _graph("AAPL@ALPACA", "5m")
    assert graph_symbol(g) == "AAPL@ALPACA"
    assert graph_bar_resolution(g) == "5m"


def test_graph_extractors_none_when_absent():
    assert graph_symbol(None) is None
    assert graph_symbol({"nodes": [{"type": "rsi", "data": {}}]}) is None
    # An unknown timeframe is ignored rather than passed through.
    assert graph_bar_resolution(_graph(timeframe="3w")) is None


# --------------------------------------------------------------------------
# _resolve_symbols: graph is authoritative
# --------------------------------------------------------------------------
_KNOWN = {
    "SPY": "SPY@ALPACA", "SPY@ALPACA": "SPY@ALPACA",
    "AAPL": "AAPL@ALPACA", "AAPL@ALPACA": "AAPL@ALPACA",
}


@pytest.fixture
def patched_filter(monkeypatch):
    from packages.copilot import tools

    async def fake_filter(_session, syms):
        out, seen = [], set()
        for s in syms:
            c = _KNOWN.get((s or "").strip().upper())
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return out

    monkeypatch.setattr(tools, "_filter_known_symbols", fake_filter)
    return tools


def test_run_uses_graph_symbol_when_no_request(patched_filter):
    """Graph says SPY -> the run executes on SPY, not a default/stale value."""
    tools = patched_filter
    out = asyncio.run(
        tools._resolve_symbols(None, uuid4(), "S", None, graph=_graph("SPY@ALPACA"))
    )
    assert out == ["SPY@ALPACA"]


def test_request_disagreeing_with_graph_is_rejected(patched_filter):
    tools = patched_filter
    with pytest.raises(tools.ToolError) as ei:
        asyncio.run(
            tools._resolve_symbols(
                None, uuid4(), "S", ["AAPL@ALPACA"], graph=_graph("SPY@ALPACA")
            )
        )
    msg = str(ei.value)
    assert "SPY@ALPACA" in msg and "AAPL@ALPACA" in msg
    assert "source of truth" in msg.lower()


def test_request_agreeing_with_graph_is_honored(patched_filter):
    """Bare 'SPY' request resolves to the graph's canonical SPY@ALPACA -> allowed."""
    tools = patched_filter
    out = asyncio.run(
        tools._resolve_symbols(None, uuid4(), "S", ["SPY"], graph=_graph("SPY@ALPACA"))
    )
    assert out == ["SPY@ALPACA"]


def test_no_graph_falls_back_to_last_backtest(patched_filter):
    """Raw-code strategy (no graph): unchanged behaviour — last backtest's symbols."""
    tools = patched_filter

    class _Res:
        def first(self):
            return (["DOGE-USD@BINANCEUS"],)

    class _Session:
        async def execute(self, *_a, **_k):
            return _Res()

    out = asyncio.run(
        tools._resolve_symbols(_Session(), uuid4(), "S", None, graph=None)
    )
    assert out == ["DOGE-USD@BINANCEUS"]


# --------------------------------------------------------------------------
# Build-time assumptions are persisted, then surfaced on the run result
# --------------------------------------------------------------------------
def test_run_backtest_surfaces_stored_assumptions(monkeypatch):
    """A strategy row carrying assumptions -> they appear on the run result."""
    from packages.copilot import tools

    stored_assumptions = [
        "Inferred a 1d timeframe (none was specified).",
        "Read 'risk 2%' as a 2% stop-loss; applied as the default.",
    ]
    strat_row = {
        "id": uuid4(), "name": "My Strat",
        "graph_json": _graph("SPY@ALPACA", "1d"),
        "assumptions": stored_assumptions,
        "params_schema": {},
    }

    async def fake_load(_s, _u, _sid):
        return strat_row
    monkeypatch.setattr(tools, "_load_strategy_or_raise", fake_load)

    async def fake_resolve(*_a, **_k):
        return types.SimpleNamespace(cls=object, source="user")
    monkeypatch.setattr(tools, "resolve_strategy", fake_resolve)
    monkeypatch.setattr(tools, "_resolve_and_validate_params", lambda *a, **k: {})

    async def fake_symbols(*_a, **_k):
        return ["SPY@ALPACA"]
    monkeypatch.setattr(tools, "_resolve_symbols", fake_symbols)

    async def fake_meta(*_a, **_k):
        return {"bar_resolution": "1d"}
    monkeypatch.setattr(tools, "_latest_backtest_meta", fake_meta)

    new_bt_id = uuid4()

    async def fake_create_backtest(*_a, **_k):
        return new_bt_id
    monkeypatch.setattr(tools, "create_backtest", fake_create_backtest)

    class _Redis:
        async def lpush(self, *_a, **_k):
            return 1

    async def fake_redis():
        return _Redis()
    monkeypatch.setattr(tools, "_get_redis", fake_redis)

    async def fake_poll(*_a, **_k):
        return "completed"
    monkeypatch.setattr(tools, "_poll_until_terminal", fake_poll)

    class _Session:
        async def commit(self):
            return None

    user = types.SimpleNamespace(id=uuid4(), org_id=uuid4())
    out = asyncio.run(
        tools._tool_run_backtest(
            {"strategy_id": str(strat_row["id"])},
            session=_Session(), user=user, registry={},
        )
    )
    assert out["assumptions"] == stored_assumptions
    assert out["bar_resolution"] == "1d"
    assert out["symbols"] == ["SPY@ALPACA"]


def test_build_persists_assumptions(monkeypatch):
    """build_strategy stores the planner + risk-default assumptions on the row."""
    from packages.copilot import tools

    captured = {}

    plan = {
        "graph": _graph("SPY@ALPACA", "1d"),
        "plan": ["step"],
        "assumptions": ["Inferred a 1d timeframe (none was specified)."],
    }

    plan_dict = {"ok": True, "name": "Strat", "assetClass": "stocks", **plan}

    def fake_plan(*_a, **_k):
        return types.SimpleNamespace(to_dict=lambda: plan_dict)
    monkeypatch.setattr(tools, "plan_graph_from_nl", fake_plan)

    # Deterministic compiler succeeds and flags the ambiguous risk default.
    def fake_compile(*_a, **_k):
        return types.SimpleNamespace(
            ok=True, source_code="src", class_name="Strat", reason=None,
            risk_flag={"message": "Read 'risk 2%' as a 2% stop-loss."},
        )
    monkeypatch.setattr(tools, "compile_graph_to_source", fake_compile)
    monkeypatch.setattr(
        tools, "validate_strategy_source",
        lambda *_a, **_k: types.SimpleNamespace(
            ok=True, class_name="Strat", params_schema={}),
    )

    async def fake_by_name(*_a, **_k):
        return None  # name is free
    monkeypatch.setattr(tools, "get_user_strategy_by_name", fake_by_name)

    async def fake_create(*_a, **kw):
        captured.update(kw)
        return uuid4()
    monkeypatch.setattr(tools, "create_user_strategy", fake_create)

    class _Session:
        async def commit(self):
            return None

    user = types.SimpleNamespace(id=uuid4(), org_id=uuid4())
    out = asyncio.run(
        tools._tool_build_strategy(
            {"description": "buy when RSI<30, risk 2%"},
            session=_Session(), user=user, registry={},
        )
    )
    # The compiler's risk default AND the planner's inferred timeframe were
    # persisted on the strategy, and echoed on the build result.
    assert captured["assumptions"] == [
        "Inferred a 1d timeframe (none was specified).",
        "Read 'risk 2%' as a 2% stop-loss.",
    ]
    assert out["assumptions"] == captured["assumptions"]


# --------------------------------------------------------------------------
# HTTP accept-time path rejects a request that disagrees with the graph
# --------------------------------------------------------------------------
def _client(monkeypatch, *, graph):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.api.deps import get_current_user_record, get_db_session
    from services.api.routers import backtests as bt

    async def fake_resolve(*_a, **_k):
        return types.SimpleNamespace(
            cls=types.SimpleNamespace(PARAMS_MODEL=object), source="user")
    monkeypatch.setattr(bt, "resolve_strategy", fake_resolve)

    async def fake_by_name(*_a, **_k):
        return {"graph_json": graph}
    monkeypatch.setattr(bt, "get_user_strategy_by_name", fake_by_name)

    app = FastAPI()
    app.include_router(bt.router)
    app.dependency_overrides[get_current_user_record] = lambda: types.SimpleNamespace(
        id=uuid4(), org_id=uuid4(), email="t@t", role="user"
    )
    app.dependency_overrides[get_db_session] = lambda: types.SimpleNamespace()
    return TestClient(app)


def test_api_rejects_symbol_disagreeing_with_graph(monkeypatch):
    client = _client(monkeypatch, graph=_graph("SPY@ALPACA", "1d"))
    r = client.post("/backtests", json={
        "strategy_name": "My Strat",
        "symbols": ["AAPL@ALPACA"],
        "bar_resolution": "1d",
    })
    assert r.status_code == 422, r.text
    msg = r.json()["detail"]["msg"].lower()
    assert "source of truth" in msg and "spy@alpaca" in msg


def test_api_rejects_timeframe_disagreeing_with_graph(monkeypatch):
    client = _client(monkeypatch, graph=_graph("SPY@ALPACA", "5m"))
    r = client.post("/backtests", json={
        "strategy_name": "My Strat",
        "symbols": ["SPY@ALPACA"],
        "bar_resolution": "1d",
    })
    assert r.status_code == 422, r.text
    msg = r.json()["detail"]["msg"].lower()
    assert "5m" in msg and "source of truth" in msg
