#!/usr/bin/env python3
"""Demo: run the LIVE engine against a seeded panel and dump the Section 8 payload.

Proves Acceptance Criterion #2: the live engine produces a signal payload with
every Section 8 field populated. Offline -- no API keys.

    python scripts/demo_live.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import os

from catalyst.store.db import Database
from catalyst.testing import synth

# Point the engine at a throwaway sqlite file and seed a firing name.
tmp = Path(tempfile.mkdtemp()) / "demo.db"
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}"

db = Database(os.environ["DATABASE_URL"])
db.bootstrap()
as_of = synth.seed_firing_name(db, "SYNX", date(2024, 1, 2))
# Add a validator-tier catalyst so we exercise the requires_review path too.
synth.seed_catalyst(db, "SYNX", knowable_at=as_of, catalyst_type="federal_award",
                    tier="validator", requires_review=True,
                    payload={"award_amount_usd": 250_000_000, "award_id": "DEMO-001"})
db.close()

from catalyst.cron import live_engine  # imported after DATABASE_URL is set

emitted = live_engine.run(as_of=as_of)
print(f"Emitted {len(emitted)} signal(s) on {as_of}\n")

# Read back the full persisted payload and confirm every Section 8 field is set.
db = Database(os.environ["DATABASE_URL"])
rows = db.execute("SELECT payload FROM signals", ())
SECTION_8_FIELDS = [
    "signal_id", "generated_at", "ticker", "direction", "catalyst_type",
    "catalyst_source", "catalyst_knowable_at", "requires_review", "instrument",
    "contract_details", "entry_zone_low", "entry_zone_high", "do_not_chase_level",
    "stop_price", "thesis_invalidation_note", "target_1", "target_2", "target_3",
    "trim_plan", "iv_rank", "iv_rank_reliable", "chain_liquidity_grade",
    "distress_metrics", "fundamental_snapshot", "confidence_bucket",
]
for r in rows:
    payload = json.loads(r["payload"])
    print(json.dumps(payload, indent=2, default=str))
    missing = [f for f in SECTION_8_FIELDS if f not in payload]
    print("\nMissing Section 8 fields:", missing or "NONE -- all populated")
db.close()
