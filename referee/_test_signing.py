"""Adversarial tests for Referee Ed25519 signing — proves a cert cannot be forged.

Run in the worker image with the production key set:
  docker run --rm -v /home/signal/app:/app -w /app -e PYTHONPATH=/app \
     -e REFEREE_ED25519_PRIVATE_KEY=<b64> app-backtest_worker python -m referee._test_signing

Covers: round-trip (genuine verifies across a fresh load), tamper (any edited
field breaks verification), forgery (no private key => cannot mint a valid
signature for altered content), and the production guard (no key => refuse; dev
key => insecure marker).
"""
from __future__ import annotations

import copy
import json
import os

from referee import signing, cert_report

PASS, FAIL = "PASS", "FAIL"
_results = []


def _check(name, cond):
    _results.append((name, bool(cond)))
    print(f"  [{PASS if cond else FAIL}] {name}")
    return cond


def sample_verdict():
    return {
        "schema": "referee.cert/1", "seed": "referee-cert-v1", "format": "equity_curve",
        "verdict": "DEPLOY", "narrative": "Clears every gate.",
        "benchmark": "cash / zero (absolute net returns)",
        "n_obs": 879,
        "cost_model": {"round_trip_bps": 20.0, "applied": False, "self_declared": True},
        "trials": {"declared_trials": 1, "self_declared": True, "provable_floor": 1,
                   "n_trials_used": 1, "declared_below_floor": False},
        "integrity": {"status": "CLEAN", "reasons": [], "flags": []},
        "metrics": {"dsr": 0.9998, "dsr_bar": 0.95, "net_sharpe_annualized": 2.27,
                    "both_halves": True, "min_trl": 141, "T": 879},
        "pbo_cscv": None,
        "noise_battery": {"status": "GREEN", "n_boot": 200, "null_passes": 6},
        "n_trials_for_deflation": 1,
    }


def _reload(signed):
    """Round-trip through JSON text to mimic a fresh process with no key state."""
    return json.loads(json.dumps(signed, default=float))


# ----------------------------------------------------------------- tests
def test_roundtrip():
    print("test_roundtrip (genuine cert verifies)")
    signed = cert_report.sign(sample_verdict())
    r = cert_report.verify(_reload(signed))
    _check("content_ok True", r["content_ok"])
    _check("signature_ok True", r["signature_ok"])
    _check("not insecure", not r["insecure"])
    _check("verification_id present", str(signed.get("verification_id", "")).startswith("RFE-"))
    # the real leak test: the actual private-key material must appear nowhere in the cert
    priv_b64 = os.environ.get(signing.PRIVATE_ENV, "")
    full = json.dumps(signed, default=float)
    _check("no private key material leaked into the cert",
           bool(priv_b64) and priv_b64 not in full)


def test_tamper():
    print("test_tamper (any edited field breaks verification)")
    signed = cert_report.sign(sample_verdict())
    for path, mutate in [
        ("verdict", lambda d: d.__setitem__("verdict", "REJECT")),
        ("metrics.dsr", lambda d: d["metrics"].__setitem__("dsr", 0.40)),
        ("trials.declared_trials", lambda d: d["trials"].__setitem__("declared_trials", 999)),
        ("narrative", lambda d: d.__setitem__("narrative", "totally fine, trust me")),
    ]:
        t = copy.deepcopy(signed)
        mutate(t)
        r = cert_report.verify(_reload(t))
        _check(f"edited {path}: content_ok False", not r["content_ok"])
        _check(f"edited {path}: signature_ok False", not r["signature_ok"])


def test_forgery():
    print("test_forgery (no private key => cannot mint a valid signature)")
    genuine = cert_report.sign(sample_verdict())
    pub = signing.load_published_public(genuine["signature"]["key_id"])

    # Attempt 1: a genuine REJECT cert, edited into a DEPLOY, keeping the old signature.
    rejected = cert_report.sign({**sample_verdict(), "verdict": "REJECT",
                                 "metrics": {**sample_verdict()["metrics"], "dsr": 0.40}})
    a1 = _reload(rejected)
    a1["verdict"] = "DEPLOY"; a1["metrics"]["dsr"] = 0.99   # forge a pass, keep old sig
    r1 = cert_report.verify(a1)
    _check("reuse-old-signature forgery rejected", not r1["signature_ok"])

    # Attempt 2: attacker recomputes content_hash + verification_id (public ops) and
    # signs with their OWN freshly generated key, keeping the genuine key_id.
    attacker_priv = signing.Ed25519PrivateKey.generate()
    a2 = _reload(genuine); a2["verdict"] = "DEPLOY"
    body = cert_report._canonical_body(a2)
    ch = cert_report._content_hash(body)
    vid = cert_report._verification_id(ch)
    a2["content_hash"] = ch; a2["verification_id"] = vid
    a2["signature"]["value"] = signing.sign(
        cert_report._signing_message(ch, vid, a2["signature"]["key_id"]), attacker_priv)
    r2 = cert_report.verify(a2)
    _check("attacker-key forgery (genuine key_id) rejected", not r2["signature_ok"])

    # Attempt 3: attacker swaps in their own key_id (key not published) => no pubkey.
    a3 = copy.deepcopy(a2); a3["signature"]["key_id"] = signing.key_id(attacker_priv.public_key())
    body3 = cert_report._canonical_body(a3); ch3 = cert_report._content_hash(body3)
    a3["content_hash"] = ch3; a3["verification_id"] = cert_report._verification_id(ch3)
    a3["signature"]["value"] = signing.sign(
        cert_report._signing_message(ch3, a3["verification_id"], a3["signature"]["key_id"]),
        attacker_priv)
    r3 = cert_report.verify(a3)
    _check("unpublished-key forgery rejected (no pubkey)", not r3["signature_ok"])

    # Attempt 4: attacker self-signs with the dev key and flags insecure.
    os.environ["REFEREE_ALLOW_INSECURE"] = "1"
    saved = os.environ.pop(signing.PRIVATE_ENV, None)
    try:
        a4 = cert_report.sign({**sample_verdict(), "verdict": "DEPLOY"})
    finally:
        if saved is not None:
            os.environ[signing.PRIVATE_ENV] = saved
        os.environ.pop("REFEREE_ALLOW_INSECURE", None)
    r4 = cert_report.verify(_reload(a4))
    _check("dev-key cert marked insecure", r4["insecure"])
    _check("dev-key cert NOT authentic (insecure rejected)",
           not (r4["content_ok"] and r4["signature_ok"] and not r4["insecure"]))

    # Sanity: the genuine cert still verifies against the published key.
    _check("genuine still verifies", cert_report.verify(_reload(genuine))["signature_ok"])
    _ = pub  # published key was loadable


def test_guard():
    print("test_guard (no key => refuse; dev key => insecure)")
    saved = os.environ.pop(signing.PRIVATE_ENV, None)
    os.environ.pop("REFEREE_ALLOW_INSECURE", None)
    try:
        raised = False
        try:
            cert_report.sign(sample_verdict())
        except signing.SigningError:
            raised = True
        _check("no key + no insecure flag => SigningError (no cert)", raised)

        os.environ["REFEREE_ALLOW_INSECURE"] = "1"
        c = cert_report.sign(sample_verdict())
        _check("insecure flag => cert produced", "signature" in c)
        _check("insecure flag => insecure:true marker", c["signature"]["insecure"] is True)
    finally:
        os.environ.pop("REFEREE_ALLOW_INSECURE", None)
        if saved is not None:
            os.environ[signing.PRIVATE_ENV] = saved


def main():
    if signing.load_private_from_env() is None:
        print("!! REFEREE_ED25519_PRIVATE_KEY not set; round-trip/tamper/forgery tests "
              "need a production key. Set it and re-run.")
        return 3
    for t in (test_roundtrip, test_tamper, test_forgery, test_guard):
        t()
    n_fail = sum(1 for _, ok in _results if not ok)
    print("=" * 60)
    print(f"{len(_results)} checks, {len(_results)-n_fail} passed, {n_fail} failed")
    print("ALL GREEN — certificates are forgery-resistant." if n_fail == 0 else "FAILURES PRESENT")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
