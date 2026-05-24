"""
User strategies API.

CRUD over user-authored strategies. Every write validates source code
via packages.strategy.validator before persisting. Reads are scoped to
the calling user.

Endpoints:
    GET    /user-strategies                  list user's strategies
    POST   /user-strategies                  create from source code
    GET    /user-strategies/{id}             fetch one (with source code)
    PUT    /user-strategies/{id}             update source / metadata
    DELETE /user-strategies/{id}             soft-delete
    POST   /user-strategies/validate         validate source without saving
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from packages.data.user_strategies import (
    create_user_strategy,
    get_user_strategy,
    get_user_strategy_by_name,
    list_user_strategies_for_user,
    soft_delete_user_strategy,
    update_user_strategy,
)
from packages.strategy.validator import (
    StrategyValidationResult,
    validate_strategy_source,
)

# Re-use the same session + current-user dependency the rest of the API uses.
from services.api.deps import (
    get_current_user_record,
    get_db_session,
)


router = APIRouter(prefix="/user-strategies", tags=["user-strategies"])


# ============================================================
# Request / response models
# ============================================================

class CreateUserStrategyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    nl_description: Optional[str] = Field(None, max_length=4000)
    source_code: str = Field(..., min_length=10, max_length=64_000)


class UpdateUserStrategyRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    nl_description: Optional[str] = Field(None, max_length=4000)
    source_code: Optional[str] = Field(None, min_length=10, max_length=64_000)


class ValidateRequest(BaseModel):
    source_code: str = Field(..., min_length=1, max_length=64_000)


class ValidateResponse(BaseModel):
    ok: bool
    errors: list[dict[str, Any]]
    class_name: Optional[str]
    params_class_name: Optional[str]
    params_schema: Optional[dict[str, Any]]


class UserStrategySummary(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    class_name: str
    params_schema: dict[str, Any]
    is_active: bool
    created_at: Any
    updated_at: Any


class UserStrategyDetail(UserStrategySummary):
    nl_description: Optional[str]
    source_code: str


class CreateUserStrategyResponse(BaseModel):
    id: UUID
    name: str
    class_name: str


# ============================================================
# Endpoints
# ============================================================

@router.post("/validate", response_model=ValidateResponse)
async def validate_endpoint(req: ValidateRequest) -> ValidateResponse:
    """Validate source without saving. Useful for the frontend live-check."""
    result = validate_strategy_source(req.source_code)
    return _validation_to_response(result)


@router.get("", response_model=list[UserStrategySummary])
async def list_endpoint(
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user_record),
) -> list[UserStrategySummary]:
    """List the calling user's strategies (active only), newest first."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be in [1, 500]")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")

    rows = await list_user_strategies_for_user(
        session, user_id=user.id, limit=limit, offset=offset,
    )
    return [_row_to_summary(r) for r in rows]


@router.get("/{strategy_id}", response_model=UserStrategyDetail)
async def get_endpoint(
    strategy_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user_record),
) -> UserStrategyDetail:
    row = await get_user_strategy(session, strategy_id=strategy_id, user_id=user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return _row_to_detail(row)


@router.post("", response_model=CreateUserStrategyResponse, status_code=201)
async def create_endpoint(
    req: CreateUserStrategyRequest,
    session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user_record),
) -> CreateUserStrategyResponse:
    """Validate + save a strategy from raw Python source."""
    # Reject duplicate name early for a friendly error
    existing = await get_user_strategy_by_name(
        session, user_id=user.id, name=req.name,
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"msg": f"You already have a strategy named '{req.name}'."},
        )

    result = validate_strategy_source(req.source_code)
    if not result.ok:
        raise HTTPException(
            status_code=422,
            detail={
                "msg": "Strategy validation failed",
                "errors": [e.as_dict() for e in result.errors],
            },
        )
    assert result.class_name is not None
    assert result.params_schema is not None

    new_id = await create_user_strategy(
        session,
        user_id=user.id,
        org_id=user.org_id,
        name=req.name,
        description=req.description,
        nl_description=req.nl_description,
        class_name=result.class_name,
        source_code=req.source_code,
        params_schema=result.params_schema,
    )

    return CreateUserStrategyResponse(
        id=new_id,
        name=req.name,
        class_name=result.class_name,
    )


@router.put("/{strategy_id}", response_model=UserStrategyDetail)
async def update_endpoint(
    strategy_id: UUID,
    req: UpdateUserStrategyRequest,
    session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user_record),
) -> UserStrategyDetail:
    """Update mutable fields. If source_code changes, re-validate."""
    existing = await get_user_strategy(session, strategy_id=strategy_id, user_id=user.id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    class_name: Optional[str] = None
    params_schema: Optional[dict[str, Any]] = None

    # Re-validate if source changed
    if req.source_code is not None:
        result = validate_strategy_source(req.source_code)
        if not result.ok:
            raise HTTPException(
                status_code=422,
                detail={
                    "msg": "Strategy validation failed",
                    "errors": [e.as_dict() for e in result.errors],
                },
            )
        assert result.class_name is not None
        assert result.params_schema is not None
        class_name = result.class_name
        params_schema = result.params_schema

    # If renaming, check no name collision
    if req.name is not None and req.name != existing["name"]:
        clash = await get_user_strategy_by_name(
            session, user_id=user.id, name=req.name,
        )
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail={"msg": f"You already have a strategy named '{req.name}'."},
            )

    updated = await update_user_strategy(
        session,
        strategy_id=strategy_id,
        user_id=user.id,
        name=req.name,
        description=req.description,
        nl_description=req.nl_description,
        class_name=class_name,
        source_code=req.source_code,
        params_schema=params_schema,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Return the updated row
    row = await get_user_strategy(session, strategy_id=strategy_id, user_id=user.id)
    assert row is not None
    return _row_to_detail(row)


@router.delete("/{strategy_id}", status_code=204)
async def delete_endpoint(
    strategy_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user_record),
) -> None:
    """Soft-delete (sets is_active=FALSE)."""
    deleted = await soft_delete_user_strategy(
        session, strategy_id=strategy_id, user_id=user.id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Strategy not found")


# ============================================================
# Helpers
# ============================================================

def _validation_to_response(result: StrategyValidationResult) -> ValidateResponse:
    return ValidateResponse(
        ok=result.ok,
        errors=[e.as_dict() for e in result.errors],
        class_name=result.class_name,
        params_class_name=result.params_class_name,
        params_schema=result.params_schema,
    )


def _row_to_summary(row: dict[str, Any]) -> UserStrategySummary:
    return UserStrategySummary(
        id=row["id"],
        name=row["name"],
        description=row.get("description"),
        class_name=row["class_name"],
        params_schema=row["params_schema"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_detail(row: dict[str, Any]) -> UserStrategyDetail:
    return UserStrategyDetail(
        id=row["id"],
        name=row["name"],
        description=row.get("description"),
        nl_description=row.get("nl_description"),
        class_name=row["class_name"],
        params_schema=row["params_schema"],
        source_code=row["source_code"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
