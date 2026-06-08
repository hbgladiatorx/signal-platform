"""Deterministic client_order_id generation for live sessions.

The BarContext order_id_factory hook lets the live runner produce stable,
namespaced ids so a redelivered bar re-submits the SAME id (broker dedup) and
strategies can still cancel by the id submit_*() returned.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone
from decimal import Decimal

from packages.strategy.base import OrderSide
from packages.strategy.context import BarContext


def _make_ctx(bar_count: int) -> BarContext:
    seq = itertools.count()
    return BarContext(
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        symbols=["BTC-USDT@BINANCEUS"],
        history={},
        positions={},
        cash=Decimal("1000"),
        bar_count=bar_count,
        order_id_factory=lambda: f"pt_abcd1234_{bar_count:05d}_{next(seq)}",
    )


def test_ids_are_deterministic_per_bar():
    a = _make_ctx(42)
    id1 = a.submit_buy_market("BTC-USDT@BINANCEUS", Decimal("1"))
    id2 = a.submit_sell_market("BTC-USDT@BINANCEUS", Decimal("1"))
    assert id1 == "pt_abcd1234_00042_0"
    assert id2 == "pt_abcd1234_00042_1"

    # Re-running the same bar produces identical ids (idempotent replay).
    b = _make_ctx(42)
    assert b.submit_buy_market("BTC-USDT@BINANCEUS", Decimal("1")) == id1


def test_cancel_references_factory_id():
    ctx = _make_ctx(7)
    oid = ctx.submit_buy_limit("BTC-USDT@BINANCEUS", Decimal("1"), Decimal("100"))
    # The strategy can cancel using the id submit returned.
    assert ctx.cancel_order(oid) is True
    assert oid in ctx.collected_cancellations()


def test_default_factory_is_random_for_backtest():
    ctx = BarContext(
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        symbols=["X"],
        history={},
        positions={},
        cash=Decimal("1000"),
    )
    oid = ctx.submit_buy_market("X", Decimal("1"))
    assert not oid.startswith("pt_")
    assert len(oid) == 8
