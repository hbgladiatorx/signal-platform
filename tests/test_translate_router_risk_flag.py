"""API/router tests: the /user-strategies/translate endpoint must surface the
risk-ambiguity flag the same way the copilot build tool does.

The detector and the stop-loss default already exist and are tested in
test_risk_ambiguity.py. These tests only guard the HTTP-boundary plumbing: a
caller entering via the API for "risk 2% per trade" must receive the populated
risk_flag (so the silent guess isn't reintroduced on this door), and the flag's
shape must match what the copilot path returns. Unambiguous risk language
("…with a 2% stop") returns no flag.

Both of the endpoint's success branches are covered:
  * the deterministic graph-compile branch (graph_json present), and
  * the LLM-translator branch (nl_description only).
"""
from __future__ import annotations

import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.deps import get_current_user_record
from services.api.routers import user_strategies as us
from packages.strategy.llm_translator import TranslationResult
from packages.strategy.risk_language import detect_risk_ambiguity


# The dict shape every path is expected to return (or None). This mirrors
# RiskFlag.to_dict() — the exact structure the copilot build tool surfaces.
_RISK_FLAG_KEYS = {
    "kind", "ambiguous", "phrase", "value", "applied_interpretation",
    "alternative_interpretation", "default_rationale", "needs_confirmation",
    "message",
}


def _client() -> TestClient:
    """A minimal app mounting only the router, with auth stubbed (no DB)."""
    app = FastAPI()
    app.include_router(us.router)
    app.dependency_overrides[get_current_user_record] = lambda: types.SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001", org_id=None, email="t@t", role="user"
    )
    return TestClient(app)


def _rsi_long_graph() -> dict:
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


# --------------------------------------------------------------------------
# Deterministic graph-compile branch (graph_json present, no LLM)
# --------------------------------------------------------------------------
def test_compile_branch_surfaces_ambiguous_flag(monkeypatch):
    # Guard: this must NOT reach the LLM. If it does, fail loudly.
    monkeypatch.setattr(
        us, "translate_nl_to_strategy",
        lambda **_k: (_ for _ in ()).throw(AssertionError("should not hit LLM")),
    )
    text = "Buy SPY when RSI < 30, risk 2% per trade"
    body = {
        "nl_description": text,
        "graph_json": _rsi_long_graph(),
        "strategy_name": "SPY RSI",
        "asset_class": "equity",
    }
    r = _client().post("/user-strategies/translate", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["risk_flag"] is not None
    assert set(data["risk_flag"]) == _RISK_FLAG_KEYS  # copilot-matching shape
    assert data["risk_flag"]["applied_interpretation"] == "stop_loss"
    assert data["risk_flag"]["alternative_interpretation"] == "position_size"
    assert data["risk_flag"]["value"] == 2.0
    assert "Confirm" in data["risk_flag"]["message"]
    # Identical to what the shared detector (and thus the copilot path) produces.
    assert data["risk_flag"] == detect_risk_ambiguity(text).to_dict()


def test_compile_branch_no_flag_for_unambiguous(monkeypatch):
    monkeypatch.setattr(
        us, "translate_nl_to_strategy",
        lambda **_k: (_ for _ in ()).throw(AssertionError("should not hit LLM")),
    )
    body = {
        "nl_description": "Buy SPY when RSI < 30, exit with a 2% stop",
        "graph_json": _rsi_long_graph(),
        "strategy_name": "SPY RSI",
        "asset_class": "equity",
    }
    r = _client().post("/user-strategies/translate", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["risk_flag"] is None


# --------------------------------------------------------------------------
# LLM-translator branch (nl_description only) — plumbs TranslationResult.risk_flag
# --------------------------------------------------------------------------
def _stub_validation():
    return types.SimpleNamespace(
        ok=True, class_name="Gen", params_class_name="GenParams",
        params_schema={}, errors=[],
    )


def test_llm_branch_surfaces_ambiguous_flag(monkeypatch):
    text = "On SPY momentum, risk 2% per trade and exit at RSI 50"
    expected = detect_risk_ambiguity(text).to_dict()

    def fake_translate(nl_description, previous_source=None, feedback=None):
        # Mirror the real translator: it computes risk_flag from the same shared
        # detector. We assert the router carries whatever it produced, unchanged.
        flag = detect_risk_ambiguity(nl_description)
        return TranslationResult(
            ok=True, source_code="# generated", class_name="Gen",
            params_class_name="GenParams", suggested_strategy_name="Gen",
            explanation="ok", risk_flag=flag.to_dict() if flag else None,
        )

    monkeypatch.setattr(us, "translate_nl_to_strategy", fake_translate)
    monkeypatch.setattr(us, "validate_strategy_source", lambda _s: _stub_validation())

    r = _client().post("/user-strategies/translate", json={"nl_description": text})
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data["risk_flag"]) == _RISK_FLAG_KEYS
    assert data["risk_flag"] == expected


def test_llm_branch_no_flag_for_unambiguous(monkeypatch):
    text = "On SPY momentum, use a 2% stop and exit at RSI 50"

    def fake_translate(nl_description, previous_source=None, feedback=None):
        flag = detect_risk_ambiguity(nl_description)
        return TranslationResult(
            ok=True, source_code="# generated", class_name="Gen",
            params_class_name="GenParams", suggested_strategy_name="Gen",
            explanation="ok", risk_flag=flag.to_dict() if flag else None,
        )

    monkeypatch.setattr(us, "translate_nl_to_strategy", fake_translate)
    monkeypatch.setattr(us, "validate_strategy_source", lambda _s: _stub_validation())

    r = _client().post("/user-strategies/translate", json={"nl_description": text})
    assert r.status_code == 200, r.text
    assert r.json()["risk_flag"] is None


def test_risk_flag_in_response_schema():
    """The field is part of the documented OpenAPI contract, not an extra."""
    props = us.TranslateResponse.model_json_schema()["properties"]
    assert "risk_flag" in props
