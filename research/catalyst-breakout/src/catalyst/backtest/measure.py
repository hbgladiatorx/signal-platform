"""MODULE 6 -- forward measurement (run BOTH, report the gap).

1. Fixed-horizon return at +3/+6/+12 months, no exit logic. Answers "does the
   signal predict outperformance" cleanly.
2. Rules-based realized P&L applying the actual stop / target ladder /
   invalidation forward. Answers "does the system capture the edge."

These functions read FORWARD prices on purpose -- that is legitimate OUTCOME
measurement, not decision-making. The decision was already locked at T using PIT
data; entry is the T+1 open. Nothing here feeds back into a past decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..signals.entryexit import EntryExitPlan

TRADING_DAYS_PER_MONTH = 21


@dataclass
class FixedHorizonResult:
    entry_price: float
    returns: dict[int, float | None] = field(default_factory=dict)  # months -> return


@dataclass
class RulesResult:
    entry_price: float
    exit_price: float
    exit_reason: str            # 'target_3' | 'stop' | 'invalidation' | 'horizon_end'
    holding_days: int
    realized_return: float
    trims: list[dict[str, Any]] = field(default_factory=list)


def fixed_horizon(entry_price: float, forward_bars: list[dict[str, Any]],
                  horizons_months: tuple[int, ...]) -> FixedHorizonResult:
    res = FixedHorizonResult(entry_price=entry_price, returns={})
    for m in horizons_months:
        idx = m * TRADING_DAYS_PER_MONTH - 1
        if 0 <= idx < len(forward_bars):
            px = _close(forward_bars[idx])
            res.returns[m] = (px - entry_price) / entry_price if px and entry_price else None
        else:
            res.returns[m] = None
    return res


def rules_based(
    entry_price: float,
    forward_bars: list[dict[str, Any]],
    plan: EntryExitPlan,
    *,
    invalidation_bar_index: int | None = None,
) -> RulesResult:
    """Walk forward applying stop, target ladder (with trims), and invalidation.

    invalidation_bar_index: if the catalyst feed showed the driver failing on a
    forward bar, the index of that bar (thesis-invalidation exit).
    """
    targets = [plan.target_1, plan.target_2, plan.target_3]
    trims = list(plan.trim_plan) if plan.trim_plan else [1.0]
    remaining = 1.0
    realized = 0.0
    executed_trims: list[dict[str, Any]] = []
    next_target = 0

    for i, bar in enumerate(forward_bars):
        hi, lo, cl = _high(bar), _low(bar), _close(bar)

        # Thesis invalidation takes precedence.
        if invalidation_bar_index is not None and i >= invalidation_bar_index:
            realized += remaining * _ret(entry_price, cl)
            return RulesResult(entry_price, cl, "invalidation", i + 1, realized, executed_trims)

        # Stop (intrabar low).
        if plan.stop_price is not None and lo is not None and lo <= plan.stop_price:
            realized += remaining * _ret(entry_price, plan.stop_price)
            return RulesResult(entry_price, plan.stop_price, "stop", i + 1, realized, executed_trims)

        # Target ladder trims (intrabar high).
        while next_target < len(targets) and targets[next_target] is not None \
                and hi is not None and hi >= targets[next_target]:
            frac = trims[next_target] if next_target < len(trims) else remaining
            frac = min(frac, remaining)
            realized += frac * _ret(entry_price, targets[next_target])
            executed_trims.append({"target": next_target + 1, "price": targets[next_target], "frac": frac})
            remaining -= frac
            next_target += 1
            if remaining <= 1e-9:
                return RulesResult(entry_price, targets[next_target - 1], "target_3",
                                   i + 1, realized, executed_trims)

    # Ran out of forward data -> mark remaining at last close.
    last = _close(forward_bars[-1]) if forward_bars else entry_price
    realized += remaining * _ret(entry_price, last)
    return RulesResult(entry_price, last, "horizon_end", len(forward_bars), realized, executed_trims)


def _ret(entry: float, px: float | None) -> float:
    return (px - entry) / entry if px and entry else 0.0


def _close(b): return _num(b.get("adj_close")) or _num(b.get("close"))
def _high(b): return _num(b.get("high"))
def _low(b): return _num(b.get("low"))


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
