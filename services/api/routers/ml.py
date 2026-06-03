"""ML models API (Phase 4): cross-backtest signal-edge models.

Every completed backtest contributes its closed trips to a per-user,
per-strategy sample store (written by the backtest worker). These endpoints let
the user see how much data has accumulated, (re)train a signal-edge model over
the *aggregate*, and read the latest trained model.

    GET  /ml/strategies                  — per-strategy sample/model stats
    POST /ml/strategies/{name}/train     — train over all accumulated samples
    GET  /ml/strategies/{name}/model     — latest trained model (404 if none)

Models are user-scoped: one user's trades never train another user's model.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from packages.ml import model_to_dict, samples_to_dataset, train_signal_edge_model
from packages.ml.persistence import (
    count_distinct_backtests,
    list_strategy_stats,
    load_latest_model,
    load_training_samples,
    save_trained_model,
)
from services.api.deps import (
    CurrentUserRecord,
    get_current_user_record,
    get_db_session,
)

router = APIRouter(prefix="/ml", tags=["ml"])


# ============================================================
# Response models
# ============================================================
class StrategyStats(BaseModel):
    strategy_name: str
    n_samples: int
    n_backtests: int
    n_profitable: int
    # Base win rate across accumulated samples (None when no samples).
    base_profit_rate: float | None = None
    model_trained_at: datetime | None = None
    model_n_samples: int | None = None
    has_model: bool = False


class TrainResult(BaseModel):
    strategy_name: str
    model_id: UUID
    n_samples: int
    n_backtests: int
    model: dict[str, Any]


class LatestModel(BaseModel):
    id: UUID
    strategy_name: str
    trained_at: datetime
    n_samples: int
    n_backtests: int
    model: dict[str, Any]


# ============================================================
# Endpoints
# ============================================================
@router.get("/strategies", response_model=list[StrategyStats])
async def list_strategies(
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[StrategyStats]:
    rows = await list_strategy_stats(session, user.id)
    out: list[StrategyStats] = []
    for r in rows:
        n = int(r["n_samples"])
        out.append(
            StrategyStats(
                strategy_name=r["strategy_name"],
                n_samples=n,
                n_backtests=int(r["n_backtests"]),
                n_profitable=int(r["n_profitable"]),
                base_profit_rate=(r["n_profitable"] / n) if n else None,
                model_trained_at=r.get("model_trained_at"),
                model_n_samples=r.get("model_n_samples"),
                has_model=r.get("model_trained_at") is not None,
            )
        )
    return out


@router.post("/strategies/{name}/train", response_model=TrainResult)
async def train_strategy(
    name: str = Path(..., description="Strategy name to train over"),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> TrainResult:
    samples = await load_training_samples(session, user.id, name)
    if not samples:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No training samples for strategy {name!r}. Run a backtest of "
                "it that produces closed trades first."
            ),
        )

    dataset = samples_to_dataset(samples)
    model = train_signal_edge_model(dataset)
    n_backtests = await count_distinct_backtests(session, user.id, name)

    model_json = {
        **model_to_dict(model),
        "feature_vocabulary": dataset.signal_names,
    }
    model_id = await save_trained_model(
        session,
        user.id,
        name,
        model_json,
        n_samples=dataset.n_samples,
        n_backtests=n_backtests,
    )
    return TrainResult(
        strategy_name=name,
        model_id=model_id,
        n_samples=dataset.n_samples,
        n_backtests=n_backtests,
        model=model_json,
    )


@router.get("/strategies/{name}/model", response_model=LatestModel)
async def get_latest_model(
    name: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> LatestModel:
    row = await load_latest_model(session, user.id, name)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No trained model for strategy {name!r}. Train one first.",
        )
    return LatestModel(
        id=row["id"],
        strategy_name=row["strategy_name"],
        trained_at=row["trained_at"],
        n_samples=row["n_samples"],
        n_backtests=row["n_backtests"],
        model=row["model_json"],
    )
