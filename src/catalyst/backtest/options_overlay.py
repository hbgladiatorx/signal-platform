"""MODULE 6 -- options overlay (STAGE TWO: only after the underlying edge is proven).

Section 9 is emphatic: do NOT start with simulated option fills. First establish
the underlying signal edge with fixed-horizon + rules-based equity P&L. THEN model
the LEAPS / spread off historical IV with a realistic bid-ask haircut, modeled
theta and vega, and marketable-limit fills widened for illiquid chains. NEVER
assume mid fills. Flag any name where historical options data is too thin to trust.

This module is intentionally gated behind `enabled` and returns a `trustworthy`
flag so thin-data names are excluded rather than silently filled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.defaults import Config, DEFAULTS


@dataclass
class OptionFill:
    side: str                  # 'long' | 'short'
    modeled_price: float
    trustworthy: bool
    note: str = ""


def model_fill(
    *,
    mid: float,
    bid: float | None,
    ask: float | None,
    open_interest: int,
    side: str = "long",
    illiquid: bool = False,
    cfg: Config = DEFAULTS,
) -> OptionFill:
    """Model a marketable-limit fill with a bid-ask haircut. Never mid.

    Buyer pays above mid toward the ask; seller receives below mid toward the
    bid. The haircut widens for illiquid chains.
    """
    b = cfg.backtest
    if bid is None or ask is None or ask <= 0 or mid <= 0:
        return OptionFill(side, mid, trustworthy=False, note="missing/zero quote")

    spread = ask - bid
    haircut = b.options_bid_ask_haircut + (b.illiquid_extra_haircut if illiquid else 0.0)
    haircut = min(haircut, 1.0)

    if side == "long":
        price = mid + haircut * (spread / 2)   # pay up toward ask
    else:
        price = mid - haircut * (spread / 2)   # receive down toward bid

    trustworthy = open_interest >= cfg.options.min_open_interest_per_leg and not illiquid
    note = "" if trustworthy else "thin options data -- flag, do not trust fill"
    return OptionFill(side, round(price, 4), trustworthy=trustworthy, note=note)


def theta_vega_decay(premium: float, theta: float, vega: float,
                     days_held: int, iv_change: float) -> float:
    """Crude modeled mark adjustment for held option: theta bleed + vega P&L."""
    return premium + theta * days_held + vega * iv_change
