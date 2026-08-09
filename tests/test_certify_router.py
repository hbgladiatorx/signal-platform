"""HTTP surface for the Referee certification engine.

Pins the contract the router must hold:
  * a valid submission returns a signed verdict that authenticates against the
    PUBLISHED public key;
  * the boundary guard: no signing key + no insecure flag => clean error, NO cert
    (no silent dev-key fallback over HTTP);
  * explicit insecure mode marks the cert insecure:true;
  * ambiguous/unverifiable evidence returns UNVERIFIABLE with a reason, signed,
    never a silent pass;
  * the public-key endpoint serves the published key;
  * the declared trial count is reflected in the response and stamped self_declared;
  * an issued cert is fetchable by its verification_id.

The referee engine, gauntlet, signing scheme and report are NOT touched — these
tests exercise the existing library through the new router only.
"""
from __future__ import annotations

import types
from uuid import uuid4

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
def _client() -> TestClient:
    from services.api.deps import get_current_user_record
    from services.api.routers import certify as certrtr

    app = FastAPI()
    app.include_router(certrtr.router)
    app.dependency_overrides[get_current_user_record] = lambda: types.SimpleNamespace(
        id=uuid4(), org_id=uuid4(), email="quant@fund.example", role="user"
    )
    return TestClient(app)


@pytest.fixture
def production_signing(tmp_path, monkeypatch):
    """A real (test-local) production key, with its public half published into a
    hermetic key store so verification resolves it. Cert output is isolated."""
    from referee import signing

    keys_dir = tmp_path / "keys"
    keys_dir.mkdir()
    monkeypatch.setattr(signing, "KEYS_DIR", str(keys_dir))
    monkeypatch.setattr(signing, "PUBLISHED_PATH", str(keys_dir / "published.json"))

    priv_b64, pub_b64 = signing.generate_keypair()
    kid = signing.key_id(signing.load_public_b64(pub_b64))
    signing.publish_public_key(pub_b64, kid, make_current=True)

    monkeypatch.setenv("REFEREE_ED25519_PRIVATE_KEY", priv_b64)
    monkeypatch.delenv("REFEREE_ALLOW_INSECURE", raising=False)
    monkeypatch.setenv("REFEREE_CERT_STORE", str(tmp_path / "certs"))
    return {"kid": kid, "pub_b64": pub_b64}


def _clean_returns(n=200, seed=7):
    """A clean, gauntlet-eligible returns series (>=60 obs, finite, not stale)."""
    rng = np.random.default_rng(seed)
    return list(np.round(rng.normal(0.0008, 0.01, n), 6))


# --------------------------------------------------------------------------
# 1) Valid submission -> signed verdict that verifies against the published key
# --------------------------------------------------------------------------
def test_valid_submission_returns_signed_cert_that_verifies(production_signing):
    c = _client()
    r = c.post("/referee/certify", json={
        "returns": _clean_returns(), "declared_trials": 1, "cost_bps": 20,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] in {"DEPLOY", "HOLD_CONDITIONAL", "REJECT", "UNVERIFIABLE"}
    assert body["insecure"] is False
    assert body["verification_id"].startswith("RFE-")
    assert body["report_url"] == f"/referee/cert/{body['verification_id']}"

    # The returned cert authenticates against the PUBLISHED public key.
    v = c.post("/referee/verify", json={"cert": body["cert"]}).json()
    assert v["content_ok"] is True
    assert v["signature_ok"] is True
    assert v["insecure"] is False
    assert v["authentic"] is True
    assert v["verification_id"] == body["verification_id"]


# --------------------------------------------------------------------------
# 2) Boundary guard — no key, no insecure flag -> error, NO cert
# --------------------------------------------------------------------------
def test_no_signing_key_refuses_and_returns_no_cert(tmp_path, monkeypatch):
    monkeypatch.delenv("REFEREE_ED25519_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("REFEREE_ALLOW_INSECURE", raising=False)
    monkeypatch.setenv("REFEREE_CERT_STORE", str(tmp_path / "certs"))

    c = _client()
    r = c.post("/referee/certify", json={
        "returns": _clean_returns(), "declared_trials": 1, "cost_bps": 20,
    })
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "signing_unavailable"
    # No cert anywhere in the refusal.
    assert "cert" not in r.json()
    assert "verification_id" not in r.json()


# --------------------------------------------------------------------------
# 3) Explicit insecure mode -> cert carries insecure:true (loud marker)
# --------------------------------------------------------------------------
def test_insecure_mode_marks_cert_insecure(tmp_path, monkeypatch):
    monkeypatch.delenv("REFEREE_ED25519_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("REFEREE_ALLOW_INSECURE", "1")
    monkeypatch.setenv("REFEREE_CERT_STORE", str(tmp_path / "certs"))

    c = _client()
    r = c.post("/referee/certify", json={
        "returns": _clean_returns(), "declared_trials": 1, "cost_bps": 20,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["insecure"] is True
    assert body["cert"]["signature"]["insecure"] is True


# --------------------------------------------------------------------------
# 4) Ambiguous / unverifiable evidence -> UNVERIFIABLE with a reason, signed
# --------------------------------------------------------------------------
def test_unverifiable_evidence_returns_unverifiable_with_reason(production_signing):
    c = _client()
    # 20 observations < MIN_OBS (60): too short to test -> UNVERIFIABLE.
    short = list(np.round(np.linspace(0.001, 0.003, 20), 6))
    r = c.post("/referee/certify", json={
        "returns": short, "declared_trials": 1, "cost_bps": 20,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "UNVERIFIABLE"
    assert body["cert"]["integrity"]["status"] == "UNVERIFIABLE"
    assert body["cert"]["integrity"]["reasons"], "must state WHY it's unverifiable"
    # Even an UNVERIFIABLE verdict is signed — never a silent drop.
    v = c.post("/referee/verify", json={"cert": body["cert"]}).json()
    assert v["signature_ok"] is True and v["content_ok"] is True


# --------------------------------------------------------------------------
# 5) Public-key endpoint serves the published key
# --------------------------------------------------------------------------
def test_pubkey_endpoint_serves_published_key(production_signing):
    c = _client()
    r = c.get("/referee/pubkey")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alg"] == "ed25519"
    assert body["key_id"] == production_signing["kid"]
    assert body["public_key_b64"] == production_signing["pub_b64"]
    assert body["published_endpoint"] == "/referee/pubkey"


# --------------------------------------------------------------------------
# 6) Declared trial count is reflected in the response + stamped self_declared
# --------------------------------------------------------------------------
def test_trial_count_reflected_and_self_declared(production_signing):
    c = _client()
    r = c.post("/referee/certify", json={
        "returns": _clean_returns(), "declared_trials": 500, "cost_bps": 30,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["declared_trials"] == 500
    assert body["n_trials_used"] >= 500            # deflation uses max(declared, floor)
    assert body["self_declared"] is True
    assert body["cert"]["trials"]["declared_trials"] == 500
    assert body["cert"]["trials"]["self_declared"] is True
    assert body["cert"]["cost_model"]["self_declared"] is True


# --------------------------------------------------------------------------
# 7) Same bar regardless of trials: more declared trials cannot improve a verdict
# --------------------------------------------------------------------------
def test_more_trials_never_loosens_the_bar(production_signing):
    c = _client()
    rets = _clean_returns(seed=11)
    at_1 = c.post("/referee/certify", json={
        "returns": rets, "declared_trials": 1, "cost_bps": 20}).json()
    at_1000 = c.post("/referee/certify", json={
        "returns": rets, "declared_trials": 1000, "cost_bps": 20}).json()
    rank = {"DEPLOY": 3, "HOLD_CONDITIONAL": 2, "REJECT": 1, "UNVERIFIABLE": 0}
    # Deflating against more trials can only hold or lower the verdict, never raise it.
    assert rank[at_1000["verdict"]] <= rank[at_1["verdict"]]
    assert at_1000["n_trials_used"] >= 1000


# --------------------------------------------------------------------------
# 8) Fetch an issued cert by verification_id; unknown id -> 404
# --------------------------------------------------------------------------
def test_fetch_cert_by_verification_id(production_signing):
    c = _client()
    issued = c.post("/referee/certify", json={
        "returns": _clean_returns(seed=5), "declared_trials": 1, "cost_bps": 20,
    }).json()
    vid = issued["verification_id"]

    got = c.get(f"/referee/cert/{vid}")
    assert got.status_code == 200, got.text
    assert got.json()["verification_id"] == vid
    assert got.json()["cert"]["content_hash"] == issued["cert"]["content_hash"]

    miss = c.get("/referee/cert/RFE-DEAD-BEEF-0000")
    assert miss.status_code == 404


# --------------------------------------------------------------------------
# 9) Inline CSV upload path (the "uploaded CSV" form of evidence)
# --------------------------------------------------------------------------
def test_csv_text_submission_is_accepted(production_signing):
    c = _client()
    vals = _clean_returns(n=120, seed=9)
    csv_text = "return\n" + "\n".join(str(v) for v in vals)
    r = c.post("/referee/certify", json={
        "csv_text": csv_text, "declared_trials": 1, "cost_bps": 20,
    })
    assert r.status_code == 200, r.text
    assert r.json()["verification_id"].startswith("RFE-")


# --------------------------------------------------------------------------
# 10) Request validation — exactly one evidence source
# --------------------------------------------------------------------------
def test_must_supply_exactly_one_evidence_source(production_signing):
    c = _client()
    none = c.post("/referee/certify", json={"declared_trials": 1, "cost_bps": 20})
    assert none.status_code == 422
    both = c.post("/referee/certify", json={
        "returns": _clean_returns(n=80), "csv_text": "return\n0.01",
        "declared_trials": 1, "cost_bps": 20,
    })
    assert both.status_code == 422
