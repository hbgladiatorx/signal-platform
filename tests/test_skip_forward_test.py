"""'Skip forward testing' — an explicit, recorded opt-out, never a silent bypass.

Pins:
  * a skip is recorded DISTINCTLY from a pass: forward_test="skipped",
    forward_test_skipped=True, while forward_started stays False (never read as
    if forward testing happened) and the strategy advances toward deployable;
  * a real paper session is "started", not "skipped";
  * the default path is unchanged (no skip -> forward_test="none", no advance);
  * the endpoint requires OOS first (can't skip a stage not reached) and is
    user-scoped (404 for others); it records forward_skipped + promoted.
"""
from __future__ import annotations

import asyncio
import types
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.copilot import state as st


# --------------------------------------------------------------------------
# compute_strategy_state: the honest forward_test record
# --------------------------------------------------------------------------
def _patch_artifacts(monkeypatch, *, has_bt, oos, has_paper):
    async def f_lb(_s, _u, _n):
        return ({"id": uuid4(), "status": "completed", "num_closed_trades": 50,
                 "sharpe_ratio": 1.0, "total_return_pct": 5.0} if has_bt else None)
    async def f_hb(_s, _u, _n): return has_bt
    async def f_lw(_s, _u, _n):
        return ({"id": uuid4(), "status": "completed", "avg_test_sharpe": 0.5,
                 "avg_test_return_pct": 1.0, "overfit_drop": 0.1} if oos else None)
    async def f_oos(_s, _u, _n): return oos
    async def f_paper(_s, _u, _n):
        return ({"id": uuid4(), "status": "running", "mode": "paper"} if has_paper else None)
    monkeypatch.setattr(st, "_latest_backtest", f_lb)
    monkeypatch.setattr(st, "_has_completed_backtest", f_hb)
    monkeypatch.setattr(st, "_latest_walkforward", f_lw)
    monkeypatch.setattr(st, "_any_oos_passed", f_oos)
    monkeypatch.setattr(st, "_latest_paper_session", f_paper)


def _state(row):
    return asyncio.run(st.compute_strategy_state(object(), user_id=uuid4(), strategy_row=row))


def test_default_path_unchanged_no_skip(monkeypatch):
    _patch_artifacts(monkeypatch, has_bt=True, oos=True, has_paper=False)
    s = _state({"id": uuid4(), "name": "X"})
    assert s["forward_test"] == "none"
    assert s["gates_passed"]["forward_test_skipped"] is False
    assert s["gates_passed"]["forward_started"] is False
    assert s["stage"] == "oos_passed"             # NOT advanced
    assert s["next_action"]["action"] == "start_forward_test"   # forward is still the default


def test_skip_recorded_distinct_from_passed(monkeypatch):
    _patch_artifacts(monkeypatch, has_bt=True, oos=True, has_paper=False)
    now = datetime.now(timezone.utc)
    s = _state({"id": uuid4(), "name": "X",
                "forward_test_skipped_at": now, "promoted_at": now})
    assert s["forward_test"] == "skipped"
    assert s["gates_passed"]["forward_test_skipped"] is True
    # the crux: a skip is NEVER recorded as forward having passed
    assert s["gates_passed"]["forward_started"] is False
    assert s["stage"] == "deployable"             # advanced toward deployable


def test_real_forward_session_is_started_not_skipped(monkeypatch):
    _patch_artifacts(monkeypatch, has_bt=True, oos=True, has_paper=True)
    s = _state({"id": uuid4(), "name": "X"})
    assert s["forward_test"] == "started"
    assert s["gates_passed"]["forward_started"] is True
    assert s["gates_passed"]["forward_test_skipped"] is False


# --------------------------------------------------------------------------
# The endpoint: control flow + that it records skip (not pass)
# --------------------------------------------------------------------------
def _client(monkeypatch, *, strategy=True, oos_passed=True, forward_started=False, calls=None):
    from services.api.deps import get_current_user_record, get_db_session
    from services.api.routers import copilot as cp

    async def fake_get(_s, *, strategy_id, user_id):
        return {"id": strategy_id, "name": "X"} if strategy else None
    monkeypatch.setattr(cp, "get_user_strategy", fake_get)

    seq = [
        {"stage": "oos_passed", "forward_test": "none",
         "gates_passed": {"oos_passed": oos_passed, "forward_started": forward_started}},
        {"stage": "deployable", "forward_test": "skipped",
         "gates_passed": {"oos_passed": True, "forward_started": False,
                          "forward_test_skipped": True}},
    ]

    async def fake_state(_s, *, user_id, strategy_row):
        return seq.pop(0) if seq else seq_last  # noqa
    monkeypatch.setattr(cp, "compute_strategy_state", fake_state)

    async def fake_set(_s, *, strategy_id, user_id, **kw):
        if calls is not None:
            calls.update(kw)
        return True
    monkeypatch.setattr(cp, "set_strategy_lifecycle_milestone", fake_set)

    class _Session:
        async def commit(self): return None

    app = FastAPI()
    app.include_router(cp.router)
    app.dependency_overrides[get_current_user_record] = lambda: types.SimpleNamespace(
        id=uuid4(), org_id=uuid4(), email="me@me", role="user")
    app.dependency_overrides[get_db_session] = lambda: _Session()
    return TestClient(app)


def test_skip_endpoint_records_skip_and_promotes(monkeypatch):
    calls: dict = {}
    c = _client(monkeypatch, oos_passed=True, calls=calls)
    r = c.post(f"/copilot/strategies/{uuid4()}/skip-forward-test")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["forward_test"] == "skipped"
    # recorded as skip + promote, NOT as a forward pass
    assert calls == {"forward_skipped": True, "promoted": True}
    assert body["state"]["gates_passed"]["forward_test_skipped"] is True
    assert body["state"]["gates_passed"]["forward_started"] is False
    assert body["state"]["stage"] == "deployable"


def test_skip_blocked_before_oos(monkeypatch):
    c = _client(monkeypatch, oos_passed=False)
    r = c.post(f"/copilot/strategies/{uuid4()}/skip-forward-test")
    assert r.status_code == 422
    assert "oos" in r.json()["detail"]["msg"].lower() or "validate" in r.json()["detail"]["msg"].lower()


def test_skip_404_for_unknown_or_other_user(monkeypatch):
    c = _client(monkeypatch, strategy=False)
    r = c.post(f"/copilot/strategies/{uuid4()}/skip-forward-test")
    assert r.status_code == 404


def test_skip_conflict_if_forward_already_started(monkeypatch):
    c = _client(monkeypatch, oos_passed=True, forward_started=True)
    r = c.post(f"/copilot/strategies/{uuid4()}/skip-forward-test")
    assert r.status_code == 409
