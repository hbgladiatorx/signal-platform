"""Strategy discovery.

Scans the `strategies/` directory for .py files, imports each one, and
collects every concrete subclass of Strategy. The result is a mapping
{strategy_name: Strategy_class} that the backtest worker / UI can consume.

Discovery is convention-based: no registration decorator needed. Drop a
file in strategies/, define a Strategy subclass, it shows up.

Files beginning with underscore are skipped (treat as private helpers).
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import Type

from packages.strategy.base import Strategy

log = logging.getLogger(__name__)


def _project_root() -> Path:
    """Return the platform root directory (one level above packages/)."""
    return Path(__file__).resolve().parents[2]


def discover_strategies(
    directory: Path | None = None,
) -> dict[str, Type[Strategy]]:
    """Find all concrete Strategy subclasses in `directory`.

    Default directory: <project_root>/strategies

    Returns a dict keyed by Strategy.name() (defaults to class __name__).
    """
    if directory is None:
        directory = _project_root() / "strategies"

    found: dict[str, Type[Strategy]] = {}
    if not directory.exists() or not directory.is_dir():
        log.warning("strategies.discovery.dir_missing path=%s", directory)
        return found

    # Ensure the project root is on sys.path so `from packages.strategy import ...`
    # works inside strategy modules.
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    for py_file in sorted(directory.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"strategies.{py_file.stem}"
        try:
            if module_name in sys.modules:
                module = importlib.reload(sys.modules[module_name])
            else:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    log.warning("strategies.discovery.spec_failed file=%s", py_file)
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
        except Exception as e:
            log.error(
                "strategies.discovery.import_failed file=%s err=%s",
                py_file, e,
            )
            continue

        for cls_name, obj in inspect.getmembers(module, inspect.isclass):
            # We want concrete subclasses defined IN THIS MODULE
            # (avoids re-discovering Strategy itself or transitively imported ones)
            if obj.__module__ != module_name:
                continue
            if not issubclass(obj, Strategy):
                continue
            if obj is Strategy:
                continue
            if inspect.isabstract(obj):
                continue
            name = obj.name()
            if name in found:
                log.warning(
                    "strategies.discovery.duplicate name=%s file=%s previous=%s",
                    name, py_file, found[name].__module__,
                )
            found[name] = obj

    return found
