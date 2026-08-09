"""Shared fixtures for the anti-bias test suite.

Everything runs offline against an in-memory sqlite panel -- no network, no API
keys. Seeding helpers live in ``catalyst.testing.synth`` (pytest-free) so the
suite and scripts/verify.py exercise identical seed logic. Seeded names are
synthetic, never the archetypes (anti-bias rule #6).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # for the top-level `config` package

from catalyst.store.db import Database  # noqa: E402

# Re-export shared seeders so existing `from conftest import seed_*` keeps working.
from catalyst.testing.synth import (  # noqa: E402,F401
    seed_universe,
    seed_prices,
    seed_fundamentals,
    seed_catalyst,
    seed_iv,
    seed_firing_name,
)


@pytest.fixture
def db() -> Database:
    d = Database("sqlite:///:memory:")
    d.bootstrap()
    yield d
    d.close()
