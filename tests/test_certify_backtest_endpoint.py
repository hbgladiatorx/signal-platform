"""POST /backtests/{id}/certify — the in-product door to the certify engine.

Pins the contract:
  * certifying your OWN backtest returns a signed verdict that verifies against
    the published key;
  * a normal low-frequency backtest reaches a REAL verdict (not UNVERIFIABLE-by-
    stale-fill) because the endpoint sources equity WITH positions_value;
  * certifying someone else's backtest is rejected (404, no existence leak);
  * no signing key -> 503, no cert (production guard honored on this path too);
  * declared trials are reflected and stamped self_declared.

The engine, intake, signing and payload builder are reused unchanged; these
tests exercise only the new endpoint wiring.
"""
from __future__ import annotations

import datetime as dt
import types
from uuid import uuid4

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# --------------------------------------------------------------------------
# Synthetic platform backtest: low-frequency, flat no-position stretches +
# 120 active bars, equity rows shaped like load_backtest_equity returns.
# --------------------------------------------------------------------------
def _equity_rows(seed=0):
    rng = np.random.default_rng(seed)
    rets, pos = [], []
    for _ in range(4):
        rets += [0.0] * 50;                       pos += [0.0] * 50
        rets += list(rng.normal(0.0, 0.01, 30));  pos += [1000.0] * 30
    base = dt.datetime(2023, 1, 2, tzinfo=dt.timezone.utc)
    eq = 10000.0
    rows = [{"ts": base, "cash": eq, "positions_value": pos[0], "total_equity": eq}]
    for i, r in enumerate(rets):
        eq *= (1.0 + r)
        rows.append({"ts": base + dt.timedelta(days=i + 1), "cash": eq - pos[i],
                     "positions_value": pos[i], "total_equity": eq})
    return rows


OWNER = uuid4()
OTHER = uuid4()


def _backtest_row(owner_id):
    return {
        "id": uuid4(), "user_id": owner_id, "status": "completed",
        "fee_rate_bps": 10, "slippage_bps": 5, "strategy_name": "SPY RSI",
    }


@pytest.fixture
def signing_env(tmp_path, monkeypatch):
    from referee import signing
    keys = tmp_path / "keys"; keys.mkdir()
    monkeypatch.setattr(signing, "KEYS_DIR", str(keys))
    monkeypatch.setattr(signing, "PUBLISHED_PATH", str(keys / "published.json"))
    priv_b64, pub_b64 = signing.generate_keypair()
    kid = signing.key_id(signing.load_public_b64(pub_b64))
    signing.publish_public_key(pub_b64, kid, make_current=True)
    monkeypatch.setenv("REFEREE_ED25519_PRIVATE_KEY", priv_b64)
    monkeypatch.delenv("REFEREE_ALLOW_INSECURE", raising=False)
    monkeypatch.setenv("REFEREE_CERT_STORE", str(tmp_path / "certs"))
    return {"kid": kid}


def _client(monkeypatch, *, bt_row, equity=None):
    from services.api.deps import get_current_user_record, get_db_session
    from services.api.routers import backtests as bt

    async def fake_load_backtest(_session, _bid):
        return bt_row
    monkeypatch.setattr(bt, "load_backtest", fake_load_backtest)

    async def fake_load_equity(_session, _bid):
        return equity if equity is not None else _equity_rows()
    monkeypatch.setattr(bt, "load_backtest_equity", fake_load_equity)

    app = FastAPI()
    app.include_router(bt.router)
    app.dependency_overrides[get_current_user_record] = lambda: types.SimpleNamespace(
        id=OWNER, org_id=uuid4(), email="me@me", role="user")
    app.dependency_overrides[get_db_session] = lambda: types.SimpleNamespace()
    return TestClient(app)


# --------------------------------------------------------------------------
# 1) Own backtest -> signed verdict that verifies + 5) trials reflected
# --------------------------------------------------------------------------
def test_certify_own_backtest_returns_verifiable_signed_cert(signing_env, monkeypatch):
    c = _client(monkeypatch, bt_row=_backtest_row(OWNER))
    r = c.post(f"/backtests/{uuid4()}/certify", json={"declared_trials": 25})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["insecure"] is False
    assert body["verification_id"].startswith("RFE-")
    # declared trials reflected + stamped self_declared
    assert body["declared_trials"] == 25
    assert body["n_trials_used"] >= 25
    assert body["self_declared"] is True
    assert body["cert"]["cost_model"]["self_declared"] is True
    # verifies against the published key (engine verify; same check /referee/verify runs)
    from referee import cert_report
    res = cert_report.verify(body["cert"])
    assert res["content_ok"] and res["signature_ok"] and not res["insecure"]


# --------------------------------------------------------------------------
# 2) Low-frequency backtest reaches a REAL verdict (exposure included)
# --------------------------------------------------------------------------
def test_low_frequency_backtest_reaches_real_verdict(signing_env, monkeypatch):
    c = _client(monkeypatch, bt_row=_backtest_row(OWNER))
    body = c.post(f"/backtests/{uuid4()}/certify", json={"declared_trials": 4}).json()
    assert body["verdict"] in {"DEPLOY", "HOLD_CONDITIONAL", "REJECT"}
    assert "stale" not in str(body["cert"].get("integrity", {})).lower()
    # the exposure column actually engaged: integrity recorded active observations
    assert "n_active_obs" in body["cert"]["integrity"]["metrics"]


# --------------------------------------------------------------------------
# 3) Someone else's backtest -> 404 (no cert, no existence leak)
# --------------------------------------------------------------------------
def test_certify_other_users_backtest_rejected(signing_env, monkeypatch):
    c = _client(monkeypatch, bt_row=_backtest_row(OTHER))   # owned by OTHER
    r = c.post(f"/backtests/{uuid4()}/certify", json={"declared_trials": 1})
    assert r.status_code == 404
    assert "cert" not in r.json()


# --------------------------------------------------------------------------
# 4) No signing key -> 503, no cert
# --------------------------------------------------------------------------
def test_no_signing_key_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("REFEREE_ED25519_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("REFEREE_ALLOW_INSECURE", raising=False)
    monkeypatch.setenv("REFEREE_CERT_STORE", str(tmp_path / "certs"))
    c = _client(monkeypatch, bt_row=_backtest_row(OWNER))
    r = c.post(f"/backtests/{uuid4()}/certify", json={"declared_trials": 1})
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "signing_unavailable"
    assert "cert" not in r.json()


# --------------------------------------------------------------------------
# Guard: an incomplete backtest can't be certified
# --------------------------------------------------------------------------
def test_incomplete_backtest_rejected(signing_env, monkeypatch):
    row = _backtest_row(OWNER); row["status"] = "running"
    c = _client(monkeypatch, bt_row=row)
    r = c.post(f"/backtests/{uuid4()}/certify", json={"declared_trials": 1})
    assert r.status_code == 422
    assert "completed" in r.json()["detail"]["msg"].lower()
