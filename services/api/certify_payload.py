"""Build the /referee/certify evidence payload from a platform backtest's equity.

Why this exists
---------------
The certify intake became exposure-aware: when the submitted CSV carries a
per-bar ``positions_value`` column, its integrity pass treats no-position flat
stretches as structurally flat (out of the market) instead of false-flagging
them as stale/forward-filled data — letting a normal low-frequency strategy
reach a real verdict instead of UNVERIFIABLE-by-stale-fill.

The platform's equity rows (``load_backtest_equity`` / ``GET /backtests/{id}/
equity``) already carry ``positions_value`` alongside ``total_equity``. This
adapter includes it in the submitted evidence so the exposure-aware path
actually engages. It is the CLIENT side of the boundary — it only formats the
CSV the engine reads; it does not touch the engine, the intake, or the gauntlet.

Contract match
--------------
The engine's intake (``referee/intake.py``) detects an equity curve from an
``equity`` column and reads the exposure column named ``positions_value`` (its
first alias). It length-validates the exposure mask against the equity series
and silently drops it on mismatch — so we emit exactly one ``positions_value``
per equity row, in order, guaranteeing alignment.

Fallback
--------
If ``positions_value`` is not available on every row (genuinely no exposure
info), we emit the bare ``timestamp,equity`` payload — byte-identical to the old
behaviour, which the engine handles with its pre-fix path.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

# The canonical exposure column name the exposure-aware intake reads first.
EXPOSURE_COLUMN = "positions_value"


def _field(row: Any, key: str) -> Any:
    """Read `key` from a row that may be a dict or an attribute object
    (e.g. EquityPointRow / a SQLAlchemy mapping / SimpleNamespace)."""
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def build_certify_csv(equity_rows: Iterable[Any]) -> Optional[str]:
    """Return the certify ``csv_text`` for a backtest's equity curve.

    Each row must expose ``ts`` and ``total_equity``; when EVERY row also exposes
    a non-null ``positions_value`` we include it (exposure-aware path engages).
    Returns the CSV string, or ``None`` if there are no usable rows (caller then
    skips certification rather than submitting empty evidence).
    """
    rows = [r for r in equity_rows]
    if not rows:
        return None

    # Include the exposure column only when present on ALL rows, so the engine's
    # length-validation never drops a partial mask.
    have_exposure = all(_field(r, EXPOSURE_COLUMN) is not None for r in rows)
    header = ("timestamp,equity," + EXPOSURE_COLUMN) if have_exposure else "timestamp,equity"

    lines = [header]
    for r in rows:
        ts = _field(r, "ts")
        eq = _field(r, "total_equity")
        if ts is None or eq is None:
            # A malformed row would misalign the series; refuse rather than emit
            # a ragged CSV the engine would mis-parse.
            return None
        if have_exposure:
            lines.append(f"{ts},{eq},{_field(r, EXPOSURE_COLUMN)}")
        else:
            lines.append(f"{ts},{eq}")
    return "\n".join(lines)


def build_certify_request(
    equity_rows: Iterable[Any],
    *,
    declared_trials: int,
    cost_bps: float,
) -> Optional[dict]:
    """Assemble the full POST /referee/certify body from a backtest's equity.

    Returns a dict ready to send (``csv_text`` + the submitter's declared trials
    and cost), or ``None`` when no usable evidence could be built. The trial
    count and cost are passed through verbatim — this adapter never alters how
    the strategy is graded, only what evidence it is graded on.
    """
    csv_text = build_certify_csv(equity_rows)
    if csv_text is None:
        return None
    return {
        "csv_text": csv_text,
        "declared_trials": declared_trials,
        "cost_bps": cost_bps,
    }
