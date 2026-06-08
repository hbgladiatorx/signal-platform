"""FlexDecimal — a Decimal that interoperates with float/int operands.

Strategy code (especially LLM-generated graph translations) naturally mixes
float parameters with indicator values, e.g. ``2.0 * ctx.atr(sym, 14)`` or
``ema - 1.5 * atr``. Plain ``Decimal`` raises ``TypeError`` the moment a float
touches it in arithmetic, which silently killed every such strategy: the engine
swallows the per-bar exception, so the backtest "completes" with zero trades.

``FlexDecimal`` is a real ``Decimal`` subclass — it stays exact for the money
layer and passes every ``isinstance(x, Decimal)`` check — but its arithmetic
dunders coerce float/int operands (via ``str`` so there is no binary-float
drift) instead of refusing them. All ``BarContext`` numeric accessors return
this type, so strategy authors can write ordinary Python without thinking about
Decimal/float boundaries.
"""

from __future__ import annotations

from decimal import Decimal

# Arithmetic operators where Decimal refuses a float operand and we want to
# coerce instead. Comparisons (<, <=, ==, …) already accept floats on Decimal,
# so they are deliberately not overridden.
_BINARY_OPS = (
    "__add__",
    "__radd__",
    "__sub__",
    "__rsub__",
    "__mul__",
    "__rmul__",
    "__truediv__",
    "__rtruediv__",
    "__floordiv__",
    "__rfloordiv__",
    "__mod__",
    "__rmod__",
    "__pow__",
    "__rpow__",
)
_UNARY_OPS = ("__neg__", "__pos__", "__abs__")


def _coerce(value: object) -> object:
    """Turn a float into an exact Decimal; leave int/Decimal/other untouched.

    int is left as-is because Decimal arithmetic already accepts it. Anything
    that is not a number falls through unchanged so the underlying Decimal op
    can return NotImplemented and Python can try the reflected operand.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    return value


class FlexDecimal(Decimal):
    """Decimal subclass whose arithmetic tolerates float/int operands."""

    __slots__ = ()


def _make_binary(name: str):
    decimal_op = getattr(Decimal, name)

    def op(self, other):
        result = decimal_op(self, _coerce(other))
        if result is NotImplemented:
            return NotImplemented
        return FlexDecimal(result)

    op.__name__ = name
    op.__qualname__ = f"FlexDecimal.{name}"
    return op


def _make_unary(name: str):
    decimal_op = getattr(Decimal, name)

    def op(self):
        return FlexDecimal(decimal_op(self))

    op.__name__ = name
    op.__qualname__ = f"FlexDecimal.{name}"
    return op


for _name in _BINARY_OPS:
    setattr(FlexDecimal, _name, _make_binary(_name))
for _name in _UNARY_OPS:
    setattr(FlexDecimal, _name, _make_unary(_name))
del _name


def to_num(value) -> FlexDecimal:
    """Coerce any supported numeric to a FlexDecimal (no binary-float drift)."""
    if isinstance(value, FlexDecimal):
        return value
    if isinstance(value, Decimal):
        return FlexDecimal(value)
    return FlexDecimal(str(value))
