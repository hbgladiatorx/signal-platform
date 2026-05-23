"""Fill simulation — convert orders into fills given the next bar's OHLC.

Market orders:
  - Fill at the next bar's open price, adjusted by slippage:
      buy:  fill_price = open * (1 + slippage)
      sell: fill_price = open * (1 - slippage)

Limit orders (GTC, persist across bars until filled):
  - BUY limit at P: fills if low <= P on any subsequent bar.
    Fill price = min(open, P).  If the bar gapped through your limit
    (open < P), you got the better price; otherwise you got your limit.
  - SELL limit at P: fills if high >= P on any subsequent bar.
    Fill price = max(open, P).
  - No slippage on limit fills: the limit price is the limit price.

Fees: a single fee_rate_bps applied to (quantity * fill_price) on both
sides regardless of order type. This approximates Binance.US's flat
taker fee (after volume tiering).
"""
from __future__ import annotations

from decimal import Decimal

import pandas as pd

from packages.backtest.types import BacktestConfig, Fill
from packages.strategy.base import Order, OrderSide, OrderType


def _decimal(v: object) -> Decimal:
    return Decimal(str(v))


def simulate_market_fill(
    order: Order,
    bar: pd.Series,
    config: BacktestConfig,
) -> Fill:
    """Fill a market order at the bar's open + slippage."""
    open_price = _decimal(bar["open"])
    if order.side == OrderSide.BUY:
        fill_price = open_price * (Decimal(1) + config.slippage)
    else:
        fill_price = open_price * (Decimal(1) - config.slippage)

    fee = (fill_price * order.quantity * config.fee_rate)

    return Fill(
        client_order_id=order.client_order_id,
        symbol=order.symbol,
        side=order.side,
        order_type=OrderType.MARKET,
        quantity=order.quantity,
        price=fill_price,
        fee=fee,
        filled_ts=bar.name,
        order_submitted_ts=order.submitted_ts,
    )


def try_fill_limit_order(
    order: Order,
    bar: pd.Series,
    config: BacktestConfig,
) -> Fill | None:
    """Attempt to fill a limit order during a bar. Returns None if not filled."""
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

    fee = fill_price * order.quantity * config.fee_rate

    return Fill(
        client_order_id=order.client_order_id,
        symbol=order.symbol,
        side=order.side,
        order_type=OrderType.LIMIT,
        quantity=order.quantity,
        price=fill_price,
        fee=fee,
        filled_ts=bar.name,
        order_submitted_ts=order.submitted_ts,
    )
