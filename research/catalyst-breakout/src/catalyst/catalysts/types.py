"""Catalyst type taxonomy + the CatalystHit record.

Every catalyst hit carries (Section 5): a catalyst_type tag, a source, and a
MANDATORY knowable_at timestamp. The backtester keys entry off knowable_at and
NEVER off the underlying event date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Structured catalysts -- reliable history, fully backtestable.
EARNINGS_SURPRISE = "earnings_surprise_guidance_raise"
ANALYST_REVISION_CLUSTER = "analyst_revision_cluster"
INSIDER_BUY_CLUSTER = "insider_buy_cluster"
NEW_INSTITUTIONAL = "new_institutional_position"

# Validator catalysts -- sparse, hard to backtest, the real edge.
FEDERAL_AWARD = "federal_award"
STRATEGIC_STAKE_13D = "strategic_stake_13d_13g"
MATERIAL_8K = "material_8k"
STRATEGIC_INVESTMENT = "strategic_investment_partnership"

STRUCTURED_TYPES = frozenset(
    {EARNINGS_SURPRISE, ANALYST_REVISION_CLUSTER, INSIDER_BUY_CLUSTER, NEW_INSTITUTIONAL}
)
VALIDATOR_TYPES = frozenset(
    {FEDERAL_AWARD, STRATEGIC_STAKE_13D, MATERIAL_8K, STRATEGIC_INVESTMENT}
)


@dataclass
class CatalystHit:
    ticker: str
    catalyst_type: str
    source: str
    knowable_at: str            # MANDATORY -- ISO date/datetime market could know.
    tier: str                   # 'structured' | 'validator'
    event_date: str | None = None
    requires_review: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.knowable_at:
            raise ValueError("CatalystHit.knowable_at is mandatory")
        if self.tier not in ("structured", "validator"):
            raise ValueError(f"bad tier: {self.tier}")
