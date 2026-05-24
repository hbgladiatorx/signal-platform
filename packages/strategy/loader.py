"""
Dynamic strategy loader.

Compiles user-strategy source code in a restricted execution environment
and returns the Strategy subclass. Uses the same `build_safe_builtins`
helper as the validator at save time — defense-in-depth.

The compile-and-load step is run on EVERY backtest, not cached, because:
  - User strategies can be edited; cached classes would be stale
  - Caching across requests requires invalidation logic we don't need
  - Compilation is fast (sub-millisecond for typical strategies)
"""
from __future__ import annotations

from typing import Any, Type

from packages.strategy.base import Strategy
from packages.strategy.validator import build_safe_builtins


class StrategyLoadError(Exception):
    """Raised when user strategy source can't be compiled or loaded."""


def load_user_strategy_class(
    source: str,
    class_name: str,
) -> Type[Strategy]:
    """
    Compile `source` in a restricted environment and return the named class.

    Args:
        source: Python source code for the strategy module.
        class_name: Name of the Strategy subclass to return.

    Returns:
        The Strategy subclass.

    Raises:
        StrategyLoadError: If the source fails to compile, the class is
            not found, or the class isn't a Strategy subclass.
    """
    try:
        code_obj = compile(source, f"<user_strategy:{class_name}>", "exec")
    except SyntaxError as e:
        raise StrategyLoadError(f"Syntax error compiling source: {e}") from e

    # Use a single namespace so class bodies can resolve module-level imports
    namespace: dict[str, Any] = {"__builtins__": build_safe_builtins()}

    try:
        exec(code_obj, namespace)  # noqa: S102
    except ImportError as e:
        raise StrategyLoadError(f"Restricted import failed: {e}") from e
    except Exception as e:
        raise StrategyLoadError(
            f"Failed to load strategy source: {type(e).__name__}: {e}"
        ) from e

    cls = namespace.get(class_name)
    if cls is None:
        raise StrategyLoadError(
            f"Class {class_name!r} not found in source. "
            f"Available names: {sorted(k for k in namespace.keys() if not k.startswith('_'))}"
        )

    if not isinstance(cls, type):
        raise StrategyLoadError(
            f"{class_name!r} is not a class (got {type(cls).__name__})"
        )

    if not issubclass(cls, Strategy):
        raise StrategyLoadError(
            f"{class_name!r} is not a Strategy subclass."
        )

    return cls
