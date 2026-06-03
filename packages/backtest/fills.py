"""Fill simulation — convert orders into fills given the next bar's OHLC.

Market orders:
  - Fill at the next bar's open price, adjusted by slippage:
      buy:  fill_price = open * (1 + slippage)
      sell: fill_price = open * (1 - slippage)

Limit orders (GTC, persist across bars until filled or cancelled or expired):
  - BUY limit at P: fills if low <= P on any subsequent bar.
    Fill price = min(open, P).  If the bar gapped through your limit
    (open < P), you got the better price; otherwise you got your limit.
  - SELL limit at P: fills if high >= P on any subsequent bar.
    Fill price = max(open, P).
  - No slippage on limit fills: the limit price is the limit price.

Volume cap (optional):
  - If config.max_pct_of_volume is set, any single fill is capped at
    `bar.volume * max_pct_of_volume`. If the order quantity exceeds
    this cap, only the cap fills and the engine requeues the remainder
    for the next bar. The Fill record has is_partial=True.
  - If the bar has zero volume and a cap is set, no fill happens and
    the order stays pending.

Fees: a single fee_rate_bps applied to (quantity * fill_price) on both
sides regardless of order type. This approximates Binance.US's flat
taker fee (after volume tiering).

Return values:
  Both simulate_market_fill() and try_fill_limit_order() return
  `(Fill, remainder_qty)` on success or `None` if no fill happened.
  `remainder_qty == 0` means a full fill; positive means the remainder
  should be requeued.
"""
from __future__ import annotations

from decimal import Decimal

import pandas as pd

from packages.backtest.types import BacktestConfig, Fill
from packages.strategy.base import Order, OrderSide, OrderType


def _decimal(v: object) -> Decimal:
    return Decimal(str(v))


def _apply_volume_cap(
    requested_qty: Decimal,
    bar_volume_raw: object,
    config: BacktestConfig,
) -> Decimal | None:
    """Apply the optional volume cap to a fill quantity.

    Returns the fillable quantity, or None if zero volume blocks the
    fill entirely. When max_pct_of_volume is None, returns requested_qty
    unchanged (preserves the no-cap, full-fill default behavior).
    """
    if config.max_pct_of_volume is None:
        return requested_qty
    bar_volume = _decimal(bar_volume_raw)
    max_fillable = bar_volume * config.max_pct_of_volume
    if max_fillable <= 0:
        return None
    return min(requested_qty, max_fillable)


def simulate_market_fill(
    order: Order,
    bar: pd.Series,
    config: BacktestConfig,
) -> tuple[Fill, Decimal] | None:
    """Fill a market order at the bar's open + slippage.

    Returns (Fill, remainder_qty) on success, or None if zero-volume
    blocks the fill entirely (only possible with volume cap enabled).
    """
    open_price = _decimal(bar["open"])

    fillable_qty = _apply_volume_cap(order.quantity, bar["volume"], config)
    if fillable_qty is None:
        return None  # zero-volume bar with cap; order persists

    if order.side == OrderSide.BUY:
        fill_price = open_price * (Decimal(1) + config.slippage)
    else:
        fill_price = open_price * (Decimal(1) - config.slippage)

    fee = config.fee_for(order.symbol, fill_price, fillable_qty)
    remainder = order.quantity - fillable_qty
    is_partial = remainder > 0

    fill = Fill(
        client_order_id=order.client_order_id,
        symbol=order.symbol,
        side=order.side,
        order_type=OrderType.MARKET,
        quantity=fillable_qty,
        price=fill_price,
        fee=fee,
        filled_ts=bar.name,
        order_submitted_ts=order.submitted_ts,
        is_partial=is_partial,
    )
    return fill, remainder


def try_fill_limit_order(
    order: Order,
    bar: pd.Series,
    config: BacktestConfig,
) -> tuple[Fill, Decimal] | None:
    """Attempt to fill a limit order during a bar.

    Returns (Fill, remainder_qty) on success, or None if the bar's
    range did not cross the limit price (or zero-volume blocks fill).
    """
    if order.limit_price is None:
        return None  # defensive; constructor validates this

    high = _decimal(bar["high"])
    low = _decimal(bar["low"])
    open_price = _decimal(bar["open"])
    limit = order.limit_price

    if order.side == OrderSide.BUY:
        # Buy limit fills if the bar's low reached down to (or below) the limit.
        if low > limit:
            return None
        fill_price = min(open_price, limit)
    else:
        # Sell limit fills if the bar's high reached up to (or above) the limit.
        if high < limit:
            return None
        fill_price = max(open_price, limit)

    fillable_qty = _apply_volume_cap(order.quantity, bar["volume"], config)
    if fillable_qty is None:
        return None  # zero-volume bar with cap; order persists

    fee = config.fee_for(order.symbol, fill_price, fillable_qty)
    remainder = order.quantity - fillable_qty
    is_partial = remainder > 0

    fill = Fill(
        client_order_id=order.client_order_id,
        symbol=order.symbol,
        side=order.side,
        order_type=OrderType.LIMIT,
        quantity=fillable_qty,
        price=fill_price,
        fee=fee,
        filled_ts=bar.name,
        order_submitted_ts=order.submitted_ts,
        is_partial=is_partial,
    )
    return fill, remainder
