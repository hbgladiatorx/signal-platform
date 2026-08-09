"""Ed25519 asymmetric signing for Referee certificates.

A certificate's entire value is authenticity. The old scheme — sha256(public-seed
‖ content) or an HMAC under a dev key — was forgeable: anyone holding the report
could edit a REJECT into a DEPLOY and recompute the signature, because the secret
was printed or shared. Asymmetric signing fixes this structurally:

  * We sign with a PRIVATE key only the server holds (REFEREE_ED25519_PRIVATE_KEY).
  * We PUBLISH the public key (committed .pub + served endpoint, later).
  * Anyone can verify a report is authentic with the public key alone, and NOBODY
    can mint a fake without the private key.

Hard production guard: if no private key is configured, signing REFUSES to produce
a certificate. A deterministic dev key exists ONLY behind an explicit
REFEREE_ALLOW_INSECURE=1 flag, and every cert it makes is stamped insecure:true.
Production never sets that flag.

No key material is ever written to a report, committed, or logged.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

PRIVATE_ENV = "REFEREE_ED25519_PRIVATE_KEY"
ALLOW_INSECURE_ENV = "REFEREE_ALLOW_INSECURE"

KEYS_DIR = os.path.join(os.path.dirname(__file__), "keys")
PUBLISHED_PATH = os.path.join(KEYS_DIR, "published.json")
PUBKEY_ENDPOINT = "/referee/pubkey"   # planned API route; the .pub is the source of truth today

# A deterministic, well-known INSECURE key for local/dev only. It is not a secret
# and must never be trusted: any cert it signs is marked insecure:true.
_DEV_SEED = hashlib.sha256(b"referee-ed25519-INSECURE-dev-key-do-not-trust").digest()


class SigningError(RuntimeError):
    """Raised when a certificate cannot be signed under the production guard."""


# ----------------------------------------------------------------- key bytes
def _priv_raw(priv: Ed25519PrivateKey) -> bytes:
    return priv.private_bytes(serialization.Encoding.Raw,
                             serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())


def _pub_raw(pub: Ed25519PublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def priv_to_b64(priv: Ed25519PrivateKey) -> str:
    return base64.b64encode(_priv_raw(priv)).decode()


def pub_to_b64(pub: Ed25519PublicKey) -> str:
    return base64.b64encode(_pub_raw(pub)).decode()


def key_id(pub: Ed25519PublicKey) -> str:
    """Stable id derived from the public key; lets us rotate keys without
    invalidating old certs (each cert records the key_id it was signed under)."""
    return hashlib.sha256(_pub_raw(pub)).hexdigest()[:16]


def generate_keypair() -> tuple[str, str]:
    """Returns (private_b64, public_b64). Private goes to a secret store only."""
    priv = Ed25519PrivateKey.generate()
    return priv_to_b64(priv), pub_to_b64(priv.public_key())


# --------------------------------------------------------------- key loading
def load_private_b64(val: str) -> Ed25519PrivateKey:
    val = val.strip()
    if val.startswith("-----"):
        return serialization.load_pem_private_key(val.encode(), password=None)
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(val))


def load_public_b64(val: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(val.strip()))


def load_private_from_env() -> Ed25519PrivateKey | None:
    val = os.environ.get(PRIVATE_ENV)
    return load_private_b64(val) if val else None


def allow_insecure() -> bool:
    return os.environ.get(ALLOW_INSECURE_ENV) == "1"


def dev_private() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_DEV_SEED)


def dev_public() -> Ed25519PublicKey:
    return dev_private().public_key()


# ----------------------------------------------------------- signer + guard
def get_signer() -> tuple[Ed25519PrivateKey, bool]:
    """Returns (private_key, insecure). Enforces the production guard:
    no real key + no explicit insecure flag => refuse to sign."""
    priv = load_private_from_env()
    if priv is not None:
        return priv, False
    if allow_insecure():
        return dev_private(), True
    raise SigningError(
        f"refusing to sign: {PRIVATE_ENV} is not set and {ALLOW_INSECURE_ENV} != 1. "
        "A Referee certificate cannot be issued without a real signing key.")


def startup_check(logger=None) -> dict:
    """Call at worker/API startup. Logs a prominent warning when insecure signing
    is enabled, and reports the current signing posture."""
    log = logger or (lambda m: print(m))
    priv = load_private_from_env()
    if priv is not None:
        kid = key_id(priv.public_key())
        log(f"referee.signing: production key loaded (key_id={kid})")
        return {"mode": "production", "key_id": kid, "insecure": False}
    if allow_insecure():
        log("=" * 70)
        log("WARNING: REFEREE INSECURE SIGNING ENABLED (dev key). Certs are marked "
            "insecure:true and MUST NOT be trusted. Never set "
            f"{ALLOW_INSECURE_ENV}=1 in production.")
        log("=" * 70)
        return {"mode": "insecure_dev", "key_id": key_id(dev_public()), "insecure": True}
    log("referee.signing: NO signing key configured; certification will refuse to "
        "issue certificates until a key is set.")
    return {"mode": "disabled", "key_id": None, "insecure": False}


# ----------------------------------------------------------- sign / verify
def sign(content: bytes, priv: Ed25519PrivateKey) -> str:
    return priv.sign(content).hex()


def verify(content: bytes, signature_hex: str, pub: Ed25519PublicKey) -> bool:
    try:
        pub.verify(bytes.fromhex(signature_hex), content)
        return True
    except Exception:   # noqa: BLE001 — any failure is a verification failure
        return False


# ----------------------------------------------------------- publishing
def publish_public_key(pub_b64: str, kid: str, *, make_current: bool = True) -> str:
    """Write <key_id>.pub and register it in published.json. Public key only."""
    os.makedirs(KEYS_DIR, exist_ok=True)
    pub_path = os.path.join(KEYS_DIR, f"{kid}.pub")
    with open(pub_path, "w") as f:
        f.write(pub_b64.strip() + "\n")
    registry = {"current": None, "keys": {}}
    if os.path.exists(PUBLISHED_PATH):
        registry = json.load(open(PUBLISHED_PATH))
    registry["keys"][kid] = pub_b64.strip()
    if make_current or registry.get("current") is None:
        registry["current"] = kid
    with open(PUBLISHED_PATH, "w") as f:
        json.dump(registry, f, indent=2)
    return pub_path


def load_published_public(kid: str | None = None) -> Ed25519PublicKey | None:
    """Load a published public key by id (or the current one). Verification only."""
    if not os.path.exists(PUBLISHED_PATH):
        return None
    registry = json.load(open(PUBLISHED_PATH))
    if kid is None:
        kid = registry.get("current")
    b64 = registry.get("keys", {}).get(kid)
    return load_public_b64(b64) if b64 else None


def public_key_for_verify(kid: str | None, insecure: bool) -> Ed25519PublicKey | None:
    """Resolve the public key a verifier should use for a given cert."""
    if insecure:
        return dev_public()
    return load_published_public(kid)


# ------------------------------------------------- verification_id lookup
def verification_id_lookup(vid: str, store_dir: str):
    """CONTRACT (reference impl; no API yet).

    A third party confirms an `RFE-...` id corresponds to an unmodified cert we
    issued by:
      1. fetching the issued cert for `vid` from an append-only issuance store
         (here: a directory of signed JSON certs we wrote at issue time), then
      2. running cert_report.verify() on it (Ed25519 + content_hash), then
      3. comparing the field they care about (verdict, DSR, ...) against what the
         seller showed them.
    Returns the stored signed cert dict, or None if `vid` was never issued. This
    function does NOT trust the caller's copy — it returns OUR copy for the caller
    to verify. A later API exposes this as GET /referee/cert/{vid}.
    """
    if not os.path.isdir(store_dir):
        return None
    for name in os.listdir(store_dir):
        if not name.endswith(".json"):
            continue
        try:
            rec = json.load(open(os.path.join(store_dir, name)))
        except Exception:   # noqa: BLE001
            continue
        if rec.get("verification_id") == vid:
            return rec
    return None
