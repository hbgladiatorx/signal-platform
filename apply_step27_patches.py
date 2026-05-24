"""
Step 27 patch applier.

Surgically patches two existing files to use the new strategy resolver:
  - services/api/routers/backtests.py
  - services/backtest_worker/main.py

The script is IDEMPOTENT: running it twice does nothing. Each patch
checks whether its marker text already exists before making any change.

Run from the repo root:

    cd ~/signal-platform
    python3 apply_step27_patches.py

The script prints what it changed (or skipped). Verify with `git diff`
afterwards.
"""
from __future__ import annotations

import pathlib
import sys


# ============================================================
# Patch 1: services/api/routers/backtests.py
# ============================================================

BACKTESTS_PATH = pathlib.Path("services/api/routers/backtests.py")

# Old import line — we'll insert new imports right after it
BACKTESTS_OLD_IMPORTS = (
    "from services.api.routers.strategies import get_strategy_registry"
)

BACKTESTS_NEW_IMPORTS = (
    "from services.api.routers.strategies import get_strategy_registry\n"
    "from packages.strategy.loader import StrategyLoadError\n"
    "from packages.strategy.resolver import StrategyNotFoundError, resolve_strategy"
)

# The strategy lookup block in the POST handler
BACKTESTS_OLD_LOOKUP = """    registry = get_strategy_registry()
    strategy_cls = registry.get(req.strategy_name)
    if strategy_cls is None:
        raise HTTPException(
            status_code=422,
            detail={
                "msg": f"Unknown strategy: {req.strategy_name!r}",
                "available": sorted(registry.keys()),
            },
        )

    # Validate params against the strategy's PARAMS_MODEL"""

BACKTESTS_NEW_LOOKUP = """    # Resolve strategy: registry first, then this user's user_strategies
    try:
        resolved = await resolve_strategy(
            session,
            user_id=user.id,
            strategy_name=req.strategy_name,
            builtin_registry=get_strategy_registry(),
        )
    except StrategyNotFoundError:
        raise HTTPException(
            status_code=422,
            detail={
                "msg": f"Unknown strategy: {req.strategy_name!r}",
                "available": sorted(get_strategy_registry().keys()),
            },
        )
    except StrategyLoadError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "msg": f"Strategy {req.strategy_name!r} failed to compile",
                "error": str(e),
            },
        )
    strategy_cls = resolved.cls

    # Validate params against the strategy's PARAMS_MODEL"""


# ============================================================
# Patch 2: services/backtest_worker/main.py
# ============================================================

WORKER_PATH = pathlib.Path("services/backtest_worker/main.py")

# Marker import — we add new imports right after it
WORKER_OLD_IMPORTS = (
    "from packages.strategy.registry import discover_strategies"
)

WORKER_NEW_IMPORTS = (
    "from packages.strategy.registry import discover_strategies\n"
    "from packages.data.db import session_scope\n"
    "from packages.strategy.loader import StrategyLoadError\n"
    "from packages.strategy.resolver import StrategyNotFoundError, resolve_strategy"
)

# Strategy lookup block inside _process_job
WORKER_OLD_LOOKUP = """        # 3a) Discover strategy
        strategy_cls = strategies_cache.get(strategy_name)
        if strategy_cls is None:
            raise RuntimeError(
                f"Strategy {strategy_name!r} not found in registry. "
                f"Known: {sorted(strategies_cache.keys())}"
            )"""

WORKER_NEW_LOOKUP = """        # 3a) Resolve strategy (built-in or user-authored)
        async with session_scope() as session:
            try:
                resolved = await resolve_strategy(
                    session,
                    user_id=header["user_id"],
                    strategy_name=strategy_name,
                    builtin_registry=strategies_cache,
                )
            except StrategyNotFoundError:
                raise RuntimeError(
                    f"Strategy {strategy_name!r} not found in built-ins or "
                    f"the owner's user_strategies."
                )
            except StrategyLoadError as e:
                raise RuntimeError(
                    f"Strategy {strategy_name!r} failed to compile: {e}"
                )
        strategy_cls = resolved.cls"""


# ============================================================
# Apply
# ============================================================

def apply_patch(path: pathlib.Path, old: str, new: str, label: str) -> bool:
    """Replace `old` with `new` in `path`. Returns True if anything changed."""
    if not path.exists():
        print(f"  [{label}] SKIP — file does not exist: {path}")
        return False

    text = path.read_text()

    # Idempotency: if new content already present, do nothing
    if new in text:
        print(f"  [{label}] SKIP — already patched")
        return False

    if old not in text:
        print(f"  [{label}] FAIL — old text not found. The file may have been edited.")
        print(f"           Looked for: {old[:120]!r}...")
        return False

    new_text = text.replace(old, new, 1)
    path.write_text(new_text)
    print(f"  [{label}] OK — applied")
    return True


def main() -> int:
    if not pathlib.Path("services").is_dir():
        print("ERROR: run this from the repo root (~/signal-platform)")
        return 1

    changes = 0

    print("Patching services/api/routers/backtests.py …")
    if apply_patch(
        BACKTESTS_PATH,
        BACKTESTS_OLD_IMPORTS,
        BACKTESTS_NEW_IMPORTS,
        "backtests.py imports",
    ):
        changes += 1
    if apply_patch(
        BACKTESTS_PATH,
        BACKTESTS_OLD_LOOKUP,
        BACKTESTS_NEW_LOOKUP,
        "backtests.py POST lookup",
    ):
        changes += 1

    print("Patching services/backtest_worker/main.py …")
    if apply_patch(
        WORKER_PATH,
        WORKER_OLD_IMPORTS,
        WORKER_NEW_IMPORTS,
        "worker imports",
    ):
        changes += 1
    if apply_patch(
        WORKER_PATH,
        WORKER_OLD_LOOKUP,
        WORKER_NEW_LOOKUP,
        "worker lookup",
    ):
        changes += 1

    print(f"\nDone. {changes} change(s) applied.")
    print("Verify with: git diff services/api/routers/backtests.py "
          "services/backtest_worker/main.py")
    return 0 if changes >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
