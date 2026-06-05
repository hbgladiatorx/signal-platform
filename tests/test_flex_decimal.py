"""Tests for FlexDecimal — the float-tolerant Decimal used by BarContext.

These guard the regression where LLM-translated strategies did ``float * atr``
and raised TypeError every bar, producing silent 0-trade backtests.
"""

from decimal import Decimal

import pytest

from packages.strategy.num import FlexDecimal, to_num


def test_is_a_real_decimal():
    x = to_num(Decimal("1.5"))
    assert isinstance(x, Decimal)
    assert isinstance(x, FlexDecimal)
    assert x == Decimal("1.5")


@pytest.mark.parametrize(
    "expr,expected",
    [
        (lambda a: 2.0 * a, Decimal("3.0")),
        (lambda a: a * 2.0, Decimal("3.0")),
        (lambda a: 2 * a, Decimal("3.0")),
        (lambda a: a + 0.5, Decimal("2.0")),
        (lambda a: 0.5 + a, Decimal("2.0")),
        (lambda a: a - 0.5, Decimal("1.0")),
        (lambda a: 3.0 - a, Decimal("1.5")),
        (lambda a: a / 2.0, Decimal("0.75")),
        (lambda a: 3.0 / a, Decimal("2")),
    ],
)
def test_float_arithmetic_does_not_raise(expr, expected):
    a = to_num(Decimal("1.5"))
    assert expr(a) == expected


def test_no_binary_float_drift():
    # 0.1 is not exactly representable as a binary float; str-coercion avoids drift.
    assert 3.0 * to_num(Decimal("0.1")) == Decimal("0.3")


def test_chained_ops_stay_flexible():
    a = to_num(Decimal("1.5"))
    # result of a float op must itself tolerate a further float op
    assert (2.0 * a) - 1.5 == Decimal("1.5")
    assert isinstance(2.0 * a, FlexDecimal)


def test_unary_ops():
    assert -to_num(Decimal("1.5")) == Decimal("-1.5")
    assert abs(to_num(Decimal("-3"))) == Decimal("3")


def test_comparisons_with_float():
    a = to_num(Decimal("1.5"))
    assert a < 2.0
    assert a > 1.0
    assert a <= 1.5


def test_mean_reversion_entry_threshold_pattern():
    # The exact shape that was failing in BTCMeanReversion.on_bar
    ema = to_num(Decimal("100"))
    atr = to_num(Decimal("1.5"))
    entry_atr_multiplier = 2.0
    threshold = ema - (entry_atr_multiplier * atr)
    assert threshold == Decimal("97")
    close = to_num(Decimal("96"))
    assert close < threshold  # entry fires
