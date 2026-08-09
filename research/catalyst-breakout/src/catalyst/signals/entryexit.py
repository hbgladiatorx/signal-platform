"""MODULE 4 -- entry / exit generator.

For every signal: entry zone, the do-not-chase reject, stop (max of ATR and
structural base-break) plus a thesis-invalidation flag, and a target ladder with
explicit trim levels. Wrapper-specific sizing fields are attached downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..pit.features import FeatureRow
from config.defaults import Config, DEFAULTS


@dataclass
class EntryExitPlan:
    entry_zone_low: float | None
    entry_zone_high: float | None
    do_not_chase_level: float | None
    do_not_chase_triggered: bool
    stop_price: float | None
    thesis_invalidation_note: str
    target_1: float | None
    target_2: float | None
    target_3: float | None
    trim_plan: list[float] = field(default_factory=list)


def build_plan(
    row: FeatureRow,
    *,
    catalyst_trigger_price: float,
    analyst_target: float | None = None,
    prior_resistance: float | None = None,
    eval_price: float | None = None,
    cfg: Config = DEFAULTS,
) -> EntryExitPlan:
    """Build the entry/exit plan.

    eval_price is the price the do-not-chase rule is checked against. In the
    backtester this is the T+1 OPEN (so some signals produce no fill); in the
    live engine it is the current price.
    """
    ee = cfg.entry_exit
    price = row.price or catalyst_trigger_price
    atr = row.atr or 0.0

    # Entry zone: base (consolidation low or 50-day) up to current price.
    base = row.base_low or (price * 0.9)
    entry_low = min(base, price)
    entry_high = price

    # Do-not-chase: reject if eval price is > N ATR above the catalyst trigger.
    do_not_chase_level = catalyst_trigger_price + ee.do_not_chase_atr_mult * atr
    check_price = eval_price if eval_price is not None else price
    do_not_chase = check_price > do_not_chase_level

    # Stop: max of ATR-based and structural base-break.
    atr_stop = price - ee.atr_stop_mult * atr
    structural_stop = (row.base_low * 0.99) if row.base_low else atr_stop
    stop_price = max(atr_stop, structural_stop) if atr else structural_stop

    # Target ladder: analyst consensus, prior resistance, measured move from base.
    measured_move = price + (price - base)  # height of base projected up.
    targets = sorted(
        t for t in (analyst_target, prior_resistance, measured_move) if t and t > price
    )
    t1 = targets[0] if len(targets) > 0 else price * 1.15
    t2 = targets[1] if len(targets) > 1 else price * 1.30
    t3 = targets[2] if len(targets) > 2 else price * 1.50

    return EntryExitPlan(
        entry_zone_low=round(entry_low, 4),
        entry_zone_high=round(entry_high, 4),
        do_not_chase_level=round(do_not_chase_level, 4),
        do_not_chase_triggered=do_not_chase,
        stop_price=round(stop_price, 4) if stop_price else None,
        thesis_invalidation_note=(
            "Trip if catalyst feed shows the driver failing "
            "(award rescinded, stake unwound, guidance walked back, 8-K turns bearish)."
        ),
        target_1=round(t1, 4),
        target_2=round(t2, 4),
        target_3=round(t3, 4),
        trim_plan=list(ee.trim_plan),
    )
