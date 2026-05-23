"""Symmetric encryption for sensitive settings at rest.

This module wraps Fernet (AES-128 in CBC mode + HMAC-SHA256) and is used
to encrypt secrets like API keys before they're written to the database.

The key is loaded from the SETTINGS_ENCRYPTION_KEY environment variable.
Fernet expects a 32-byte key, urlsafe-base64 encoded with `=` padding.
We accept both padded and unpadded keys (and add padding if missing) to
tolerate environments where shells strip trailing `=` characters.

Usage:

    from packages.core.encryption import encrypt_json, decrypt_json

    blob = encrypt_json({"api_key": "abc", "secret_key": "def"})
    # blob is a bytes object suitable for BYTEA columns.

    payload = decrypt_json(blob)
    # payload == {"api_key": "abc", "secret_key": "def"}

NEVER log or print decrypted payloads. NEVER write decrypted payloads
back to the database. Decrypt only at the moment of outbound use.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(Exception):
    """Raised when encryption setup or operations fail."""


def _pad_key(raw: str) -> bytes:
    """Add missing urlsafe-base64 padding if needed."""
    s = raw.strip()
    s += "=" * (-len(s) % 4)
    return s.encode("ascii")


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    raw = os.environ.get("SETTINGS_ENCRYPTION_KEY")
    if not raw:
        raise EncryptionError(
            "SETTINGS_ENCRYPTION_KEY not set; cannot initialize Fernet"
        )
    try:
        return Fernet(_pad_key(raw))
    except (ValueError, TypeError) as exc:
        raise EncryptionError(
            "SETTINGS_ENCRYPTION_KEY is not a valid Fernet key "
            "(32 bytes, urlsafe-base64)"
        ) from exc


def encrypt_json(payload: dict[str, Any]) -> bytes:
    """
    Serialize `payload` as JSON, encrypt, return ciphertext bytes.

    The returned bytes are a Fernet token: base64-encoded version+timestamp+
    IV+ciphertext+HMAC. Safe to store directly in a BYTEA column.
    """
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return _get_fernet().encrypt(data)


def decrypt_json(token: bytes) -> dict[str, Any]:
    """
    Decrypt a Fernet token (BYTEA from DB) and return the parsed JSON dict.

    Raises EncryptionError if the token is tampered with, was encrypted with
    a different key, or contains invalid JSON.
    """
    try:
        plaintext = _get_fernet().decrypt(token)
    except InvalidToken as exc:
        raise EncryptionError(
            "Invalid token: tampered, wrong key, or corrupt ciphertext"
        ) from exc
    try:
        return json.loads(plaintext.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EncryptionError("Decrypted payload is not valid JSON") from exc
