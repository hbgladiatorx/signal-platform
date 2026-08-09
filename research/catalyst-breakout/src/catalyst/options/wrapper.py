"""MODULE 3 -- options wrapper engine (the four-quadrant decision).

Given a candidate's chain (greeks/IV/OI/volume/quotes), IV rank, catalyst window,
and chain liquidity, choose the instrument:

  liquid + multi-quarter window + IV low/mid  -> LEAPS  (delta ~0.60-0.70, expiry
                                                 past catalyst resolution)
  liquid + IV high                            -> debit CALL SPREAD (finance rich vol)
  thin chain OR slow-grind catalyst           -> COMMON stock
  microcap / no usable chain                  -> REJECT for options (common or skip)

Liquidity gates (cfg.options): min OI/leg, max bid-ask % of premium, min volume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from config.defaults import Config, DEFAULTS

LEAPS = "LEAPS"
SPREAD = "SPREAD"
COMMON = "COMMON"
REJECT = "REJECT"


@dataclass
class WrapperDecision:
    instrument: str
    chain_liquidity_grade: str          # 'A' | 'B' | 'C' | 'F'
    iv_rank: float | None
    iv_rank_reliable: bool
    contract_details: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    defer_sizing_to_human: bool = False


def _contract_liquid(c: dict[str, Any], cfg: Config) -> bool:
    o = cfg.options
    oi = c.get("open_interest", 0) or 0
    vol = c.get("day", {}).get("volume", c.get("volume", 0)) or 0
    bid = c.get("last_quote", {}).get("bid", c.get("bid"))
    ask = c.get("last_quote", {}).get("ask", c.get("ask"))
    if oi < o.min_open_interest_per_leg or vol < o.min_contract_volume:
        return False
    if bid is None or ask is None or ask <= 0:
        return False
    mid = (bid + ask) / 2
    if mid <= 0:
        return False
    return (ask - bid) / mid <= o.max_bid_ask_pct_of_premium


def grade_chain(chain: list[dict[str, Any]], cfg: Config) -> str:
    if not chain:
        return "F"
    liquid = sum(1 for c in chain if _contract_liquid(c, cfg))
    frac = liquid / len(chain)
    if frac >= 0.5:
        return "A"
    if frac >= 0.25:
        return "B"
    if frac > 0:
        return "C"
    return "F"


def select_wrapper(
    *,
    chain: list[dict[str, Any]],
    spot: float,
    iv_rank: float | None,
    iv_rank_reliable: bool,
    catalyst_resolution: date | None,
    as_of: date,
    target_price: float | None,
    slow_grind: bool = False,
    market_cap: float | None = None,
    cfg: Config = DEFAULTS,
) -> WrapperDecision:
    o = cfg.options
    grade = grade_chain(chain, cfg)

    # Microcap / no usable chain -> reject for options.
    if grade == "F" or (market_cap is not None and market_cap < cfg.screen.market_cap_floor_usd):
        return WrapperDecision(
            instrument=COMMON if grade in ("C", "B") else REJECT,
            chain_liquidity_grade=grade, iv_rank=iv_rank, iv_rank_reliable=iv_rank_reliable,
            rationale="No usable chain / microcap -> common-only or skip.",
        )

    # Thin chain or slow-grind catalyst -> common.
    if grade in ("B", "C") or slow_grind:
        return WrapperDecision(
            instrument=COMMON, chain_liquidity_grade=grade,
            iv_rank=iv_rank, iv_rank_reliable=iv_rank_reliable,
            rationale="Thin chain or slow-grind catalyst -> common stock.",
        )

    # Liquid chain. If IV rank unreliable, output direction/entry, defer sizing.
    if not iv_rank_reliable or iv_rank is None:
        return WrapperDecision(
            instrument=COMMON, chain_liquidity_grade=grade,
            iv_rank=iv_rank, iv_rank_reliable=False, defer_sizing_to_human=True,
            rationale="IV rank unreliable (<60d history) -> defer options sizing to human.",
        )

    # Four-quadrant: low/mid IV -> LEAPS; high IV -> debit call spread.
    if iv_rank <= o.iv_rank_split_threshold:
        contract = _pick_leaps(chain, spot, catalyst_resolution, as_of, cfg)
        return WrapperDecision(
            instrument=LEAPS if contract else COMMON, chain_liquidity_grade=grade,
            iv_rank=iv_rank, iv_rank_reliable=True, contract_details=contract or {},
            rationale="Liquid + multi-quarter window + low/mid IV -> LEAPS.",
        )
    else:
        legs = _pick_call_spread(chain, spot, target_price, as_of, cfg)
        return WrapperDecision(
            instrument=SPREAD if legs else COMMON, chain_liquidity_grade=grade,
            iv_rank=iv_rank, iv_rank_reliable=True, contract_details=legs or {},
            rationale="Liquid + high IV -> debit call spread to finance rich vol.",
        )


def _pick_leaps(chain, spot, resolution, as_of, cfg) -> dict[str, Any] | None:
    """Longest liquid expiry landing past catalyst resolution, delta ~0.6-0.7."""
    o = cfg.options
    min_expiry = resolution or as_of
    candidates = []
    for c in chain:
        d = c.get("details", {})
        if d.get("contract_type") != "call":
            continue
        exp = d.get("expiration_date")
        if not exp or exp <= min_expiry.isoformat():
            continue
        delta = (c.get("greeks") or {}).get("delta")
        if delta is None or not (o.leaps_target_delta_low <= delta <= o.leaps_target_delta_high):
            continue
        if not _contract_liquid(c, cfg):
            continue
        candidates.append((exp, abs(delta - (o.leaps_target_delta_low + o.leaps_target_delta_high) / 2), c))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=False)
    # Longest expiry, then closest to target delta.
    candidates.sort(key=lambda x: (x[0],), reverse=True)
    _, _, best = candidates[0]
    return {
        "type": "call",
        "strike": best["details"].get("strike_price"),
        "expiry": best["details"].get("expiration_date"),
        "delta": (best.get("greeks") or {}).get("delta"),
        "iv": best.get("implied_volatility"),
    }


def _pick_call_spread(chain, spot, target_price, as_of, cfg) -> dict[str, Any] | None:
    """Long leg near the money, short leg at the target."""
    calls = [c for c in chain if c.get("details", {}).get("contract_type") == "call"
             and _contract_liquid(c, cfg)]
    if not calls:
        return None
    near = min(calls, key=lambda c: abs((c["details"].get("strike_price") or 0) - spot))
    tp = target_price or spot * 1.3
    short = min(calls, key=lambda c: abs((c["details"].get("strike_price") or 0) - tp))
    if short["details"].get("strike_price") <= near["details"].get("strike_price"):
        return None
    return {
        "type": "debit_call_spread",
        "long_strike": near["details"].get("strike_price"),
        "short_strike": short["details"].get("strike_price"),
        "expiry": near["details"].get("expiration_date"),
        "long_iv": near.get("implied_volatility"),
        "short_iv": short.get("implied_volatility"),
    }
