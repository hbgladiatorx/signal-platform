"""MODULE 5 -- live signal output.

Assembles the full Section 8 payload (every field populated), persists to the
Supabase `signals` table, and pushes to a channel. Expected volume: under one new
entry per day (Section 1: the system is selective by design).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from typing import Any

from ..pit.features import FeatureRow
from ..screen.distressed import ScreenResult
from ..catalysts.types import CatalystHit
from ..options.wrapper import WrapperDecision
from .entryexit import EntryExitPlan
from ..store.db import Database


@dataclass
class SignalPayload:
    signal_id: str
    generated_at: str
    ticker: str
    direction: str
    catalyst_type: str
    catalyst_source: str
    catalyst_knowable_at: str
    requires_review: bool
    instrument: str
    contract_details: dict[str, Any]
    entry_zone_low: float | None
    entry_zone_high: float | None
    do_not_chase_level: float | None
    stop_price: float | None
    thesis_invalidation_note: str
    target_1: float | None
    target_2: float | None
    target_3: float | None
    trim_plan: list[float]
    iv_rank: float | None
    iv_rank_reliable: bool
    chain_liquidity_grade: str
    distress_metrics: dict[str, Any]
    fundamental_snapshot: dict[str, Any]
    confidence_bucket: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


def _confidence_bucket(catalyst: CatalystHit, screen: ScreenResult, wrapper: WrapperDecision) -> str:
    """Coarse bucket. Validator-tier catalysts with a clean screen rank highest;
    anything needing review or on a weak chain is throttled down."""
    if catalyst.tier == "validator" and screen.passed and wrapper.chain_liquidity_grade in ("A", "B"):
        return "high"
    if catalyst.tier == "validator" or (screen.passed and wrapper.chain_liquidity_grade == "A"):
        return "medium"
    return "low"


def build_payload(
    *,
    generated_at: str,
    row: FeatureRow,
    screen: ScreenResult,
    catalyst: CatalystHit,
    wrapper: WrapperDecision,
    plan: EntryExitPlan,
    direction: str = "long",
) -> SignalPayload:
    return SignalPayload(
        signal_id=str(uuid.uuid4()),
        generated_at=generated_at,
        ticker=row.ticker,
        direction=direction,
        catalyst_type=catalyst.catalyst_type,
        catalyst_source=catalyst.source,
        catalyst_knowable_at=catalyst.knowable_at,
        requires_review=catalyst.requires_review,
        instrument=wrapper.instrument,
        contract_details=wrapper.contract_details,
        entry_zone_low=plan.entry_zone_low,
        entry_zone_high=plan.entry_zone_high,
        do_not_chase_level=plan.do_not_chase_level,
        stop_price=plan.stop_price,
        thesis_invalidation_note=plan.thesis_invalidation_note,
        target_1=plan.target_1,
        target_2=plan.target_2,
        target_3=plan.target_3,
        trim_plan=plan.trim_plan,
        iv_rank=wrapper.iv_rank,
        iv_rank_reliable=wrapper.iv_rank_reliable,
        chain_liquidity_grade=wrapper.chain_liquidity_grade,
        distress_metrics=screen.distress_metrics,
        fundamental_snapshot=row.fundamental_snapshot,
        confidence_bucket=_confidence_bucket(catalyst, screen, wrapper),
    )


def persist(db: Database, payload: SignalPayload) -> None:
    db.execute(
        "INSERT INTO signals (signal_id, generated_at, ticker, payload) VALUES (?, ?, ?, ?)",
        (payload.signal_id, payload.generated_at, payload.ticker, payload.to_json()),
    )


def push(payload: SignalPayload, webhook_url: str | None) -> bool:
    """Push to the configured channel. Returns True on success, False if no-op."""
    if not webhook_url:
        return False
    try:
        import requests

        resp = requests.post(webhook_url, json=json.loads(payload.to_json()), timeout=15)
        return resp.ok
    except Exception:
        return False
