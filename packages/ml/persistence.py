"""Persistence for the cross-backtest learning store (Phase 4).

Two concerns, both scoped by ``user_id`` so models never blend one user's
trades into another's:

  * ``ml_training_samples`` — the accumulated feature/label rows. Writing a
    backtest's samples is idempotent (delete-by-backtest then insert), so a
    re-run replaces rather than duplicates.
  * ``ml_models`` — the trained-model registry; "latest per strategy" wins.

Sample feature maps round-trip through JSONB as ``{signal_name: value|null}``.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from packages.ml.dataset import FeatureSample


# ============================================================
# Training samples
# ============================================================
async def save_training_samples(
    conn: AsyncConnection,
    backtest_id: UUID,
    user_id: UUID,
    strategy_name: str,
    samples: list[FeatureSample],
) -> None:
    """Replace this backtest's training samples with `samples` (idempotent).

    Always deletes first so re-processing a backtest can't double-count. A run
    with no closed trips simply leaves the store unchanged for that backtest.
    """
    await conn.execute(
        text("DELETE FROM ml_training_samples WHERE backtest_id = :bid"),
        {"bid": backtest_id},
    )
    if not samples:
        return

    rows = [
        {
            "backtest_id": backtest_id,
            "user_id": user_id,
            "strategy_name": strategy_name,
            "symbol": s.symbol,
            "entry_ts": s.entry_ts,
            "profitable": s.profitable,
            "net_pnl": s.net_pnl,
            "features": json.dumps(s.signal_values),
        }
        for s in samples
    ]
    await conn.execute(
        text("""
            INSERT INTO ml_training_samples (
                backtest_id, user_id, strategy_name, symbol,
                entry_ts, profitable, net_pnl, features
            ) VALUES (
                :backtest_id, :user_id, :strategy_name, :symbol,
                :entry_ts, :profitable, :net_pnl, CAST(:features AS JSONB)
            )
        """),
        rows,
    )


async def load_training_samples(
    conn: AsyncConnection,
    user_id: UUID,
    strategy_name: str,
) -> list[FeatureSample]:
    """All accumulated samples for one user's strategy, oldest entry first."""
    result = await conn.execute(
        text("""
            SELECT symbol, entry_ts, profitable, net_pnl, features
            FROM ml_training_samples
            WHERE user_id = :user_id AND strategy_name = :strategy_name
            ORDER BY entry_ts NULLS LAST, id
        """),
        {"user_id": user_id, "strategy_name": strategy_name},
    )
    samples: list[FeatureSample] = []
    for row in result.mappings().all():
        features = row["features"] or {}
        # JSONB comes back as a dict; values are float or None.
        signal_values: dict[str, float | None] = {
            name: (float(v) if v is not None else None)
            for name, v in features.items()
        }
        samples.append(
            FeatureSample(
                symbol=row["symbol"],
                entry_ts=row["entry_ts"],
                profitable=bool(row["profitable"]),
                net_pnl=float(row["net_pnl"]),
                signal_values=signal_values,
            )
        )
    return samples


# ============================================================
# Trained models
# ============================================================
async def save_trained_model(
    conn: AsyncConnection,
    user_id: UUID,
    strategy_name: str,
    model_json: dict[str, Any],
    n_samples: int,
    n_backtests: int,
) -> UUID:
    """Insert a trained model; returns its new id. Newest is the live one."""
    result = await conn.execute(
        text("""
            INSERT INTO ml_models (
                user_id, strategy_name, n_samples, n_backtests, model_json
            ) VALUES (
                :user_id, :strategy_name, :n_samples, :n_backtests,
                CAST(:model_json AS JSONB)
            )
            RETURNING id
        """),
        {
            "user_id": user_id,
            "strategy_name": strategy_name,
            "n_samples": n_samples,
            "n_backtests": n_backtests,
            "model_json": json.dumps(model_json),
        },
    )
    return result.scalar_one()


async def load_latest_model(
    conn: AsyncConnection,
    user_id: UUID,
    strategy_name: str,
) -> dict[str, Any] | None:
    """Most-recently-trained model for a user's strategy, or None."""
    result = await conn.execute(
        text("""
            SELECT id, strategy_name, trained_at, n_samples, n_backtests, model_json
            FROM ml_models
            WHERE user_id = :user_id AND strategy_name = :strategy_name
            ORDER BY trained_at DESC
            LIMIT 1
        """),
        {"user_id": user_id, "strategy_name": strategy_name},
    )
    row = result.mappings().first()
    return dict(row) if row else None


# ============================================================
# Per-strategy stats (for the ML overview page)
# ============================================================
async def list_strategy_stats(
    conn: AsyncConnection, user_id: UUID
) -> list[dict[str, Any]]:
    """For each strategy the user has samples or models for: sample/backtest
    counts and the latest trained model's timestamp + sample count."""
    result = await conn.execute(
        text("""
            WITH sample_stats AS (
                SELECT strategy_name,
                       COUNT(*)                       AS n_samples,
                       COUNT(DISTINCT backtest_id)    AS n_backtests,
                       SUM((profitable)::int)         AS n_profitable
                FROM ml_training_samples
                WHERE user_id = :user_id
                GROUP BY strategy_name
            ),
            latest_model AS (
                SELECT DISTINCT ON (strategy_name)
                       strategy_name, trained_at, n_samples AS model_n_samples
                FROM ml_models
                WHERE user_id = :user_id
                ORDER BY strategy_name, trained_at DESC
            )
            SELECT
                COALESCE(s.strategy_name, m.strategy_name) AS strategy_name,
                COALESCE(s.n_samples, 0)        AS n_samples,
                COALESCE(s.n_backtests, 0)      AS n_backtests,
                COALESCE(s.n_profitable, 0)     AS n_profitable,
                m.trained_at                    AS model_trained_at,
                m.model_n_samples               AS model_n_samples
            FROM sample_stats s
            FULL OUTER JOIN latest_model m USING (strategy_name)
            ORDER BY strategy_name
        """),
        {"user_id": user_id},
    )
    return [dict(row) for row in result.mappings().all()]


async def count_distinct_backtests(
    conn: AsyncConnection, user_id: UUID, strategy_name: str
) -> int:
    """How many distinct backtests contributed samples for this strategy."""
    result = await conn.execute(
        text("""
            SELECT COUNT(DISTINCT backtest_id) AS n
            FROM ml_training_samples
            WHERE user_id = :user_id AND strategy_name = :strategy_name
        """),
        {"user_id": user_id, "strategy_name": strategy_name},
    )
    return int(result.scalar_one() or 0)
