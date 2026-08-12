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

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.data.user_strategies import (
    create_user_strategy,
    get_user_strategy,
    get_user_strategy_by_name,
    list_user_strategies_for_user,
    soft_delete_user_strategy,
    update_user_strategy,
)
from packages.core.ai_provider import bind_request_ai_config
from packages.strategy.graph_compiler import compile_graph_to_source
from packages.strategy.graph_planner import plan_graph_from_code, plan_graph_from_nl
from packages.strategy.llm_translator import (
    TranslationResult,
    translate_nl_to_strategy,
)
from packages.strategy.validator import (
    StrategyValidationResult,
    validate_strategy_source,
)

log = logging.getLogger(__name__)

# Re-use the same session + current-user dependency the rest of the API uses.
from services.api.deps import (
    get_current_user_record,
    get_db_session,
)
# For built-in name collision check
from services.api.routers.strategies import get_strategy_registry


router = APIRouter(prefix="/user-strategies", tags=["user-strategies"])


# ============================================================
# Request / response models
# ============================================================

class CreateUserStrategyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    nl_description: Optional[str] = Field(None, max_length=4000)
    source_code: str = Field(..., min_length=10, max_length=64_000)
    # thebayn visual builder metadata (editable view; source stays runnable).
    graph_json: Optional[dict[str, Any]] = None
    asset_class: Optional[str] = Field(None, max_length=32)


class UpdateUserStrategyRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    nl_description: Optional[str] = Field(None, max_length=4000)
    source_code: Optional[str] = Field(None, min_length=10, max_length=64_000)
    graph_json: Optional[dict[str, Any]] = None
    asset_class: Optional[str] = Field(None, max_length=32)


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
    graph_json: Optional[dict[str, Any]] = None
    asset_class: Optional[str] = None
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
    # Reject names that collide with built-in strategies (so users can't
    # shadow them — the resolver looks in the built-in registry first).
    builtin_registry = get_strategy_registry()
    if req.name in builtin_registry:
        raise HTTPException(
            status_code=409,
            detail={
                "msg": (
                    f"Name {req.name!r} collides with a built-in strategy. "
                    "Pick a different name."
                ),
            },
        )

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

    try:
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
            graph_json=req.graph_json,
            asset_class=req.asset_class,
        )
    except IntegrityError:
        # Name collides with an existing active strategy (raced past the pre-check,
        # or before the partial-unique migration, a soft-deleted one). Clean 409
        # instead of a 500.
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"msg": f"You already have a strategy named '{req.name}'."},
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

    # If renaming, check no name collision (with built-ins or other user strategies)
    if req.name is not None and req.name != existing["name"]:
        builtin_registry = get_strategy_registry()
        if req.name in builtin_registry:
            raise HTTPException(
                status_code=409,
                detail={
                    "msg": (
                        f"Name {req.name!r} collides with a built-in strategy. "
                        "Pick a different name."
                    ),
                },
            )
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
        graph_json=req.graph_json,
        asset_class=req.asset_class,
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
# Translate endpoint (Step 28)
# ============================================================

class TranslateRequest(BaseModel):
    nl_description: str = Field(
        ..., min_length=10, max_length=4000,
        description="Natural language description of the strategy.",
    )
    previous_source: Optional[str] = Field(
        None, max_length=64_000,
        description="Previous attempt's source code (for refinement turns).",
    )
    feedback: Optional[str] = Field(
        None, max_length=2000,
        description="What to change about the previous attempt (required if previous_source provided).",
    )
    # When the request comes from the visual builder, the structured graph is
    # sent too. We compile it deterministically (honouring every entry/exit/
    # risk node) and only fall back to the LLM if the graph has constructs the
    # compiler doesn't support.
    graph_json: Optional[dict[str, Any]] = Field(default=None)
    strategy_name: Optional[str] = Field(default=None, max_length=200)
    asset_class: Optional[str] = Field(default=None, max_length=40)


class TranslateResponse(BaseModel):
    """LLM-generated source plus the validator's verdict.

    `ok` reflects validation. If the LLM produced code but validation
    rejected it, `ok=False` and validation_errors contains the failures —
    the frontend can show them as 'try refining' hints.

    If the LLM itself failed (timeout, no API key, no tool_use), `ok=False`
    and llm_error is set with no source_code.
    """
    ok: bool
    source_code: Optional[str] = None
    class_name: Optional[str] = None
    params_class_name: Optional[str] = None
    suggested_strategy_name: Optional[str] = None
    params_schema: Optional[dict[str, Any]] = None
    explanation: Optional[str] = None
    validation_errors: list[dict[str, Any]] = []
    llm_error: Optional[str] = None
    # Machine-readable clarification flag when the description's risk language was
    # ambiguous between position-size and stop-loss (e.g. bare "risk 2% per
    # trade"). Same shape the copilot build tool returns, from the same shared
    # detector — so a frontend consuming either path sees one structure. None
    # when risk language was unambiguous or absent. See risk_language.py.
    risk_flag: Optional[dict[str, Any]] = None
    input_tokens: int = 0
    output_tokens: int = 0


@router.post("/translate", response_model=TranslateResponse)
async def translate_endpoint(
    req: TranslateRequest,
    user=Depends(get_current_user_record),
    session: AsyncSession = Depends(get_db_session),
) -> TranslateResponse:
    """Generate strategy Python source from a natural-language description.

    The flow:
      1. Call Claude with our system prompt + the user's NL description
      2. The LLM responds via the emit_strategy_code tool (structured)
      3. We run the generated source through the same validator used for
         hand-written strategies (AST + restricted exec)
      4. We return both the source and the validation verdict

    This endpoint does NOT save the strategy. The frontend can show the
    code to the user, who can then POST it to /user-strategies if happy.
    """
    if req.previous_source and not req.feedback:
        raise HTTPException(
            status_code=422,
            detail={"msg": "feedback is required when previous_source is provided"},
        )

    # ---- Deterministic graph compile (preferred for builder graphs) ----
    # Only on a fresh build (not a refinement turn). Guarantees the generated
    # code matches the drawn graph — entry AND exit AND risk nodes — instead of
    # trusting the LLM, which has silently dropped exit rules.
    if req.graph_json and not req.previous_source:
        compiled = compile_graph_to_source(
            name=req.strategy_name or "Strategy",
            asset_class=req.asset_class or "stocks",
            graph=req.graph_json,
            description=req.nl_description,
        )
        if compiled.ok and compiled.source_code:
            validation = validate_strategy_source(compiled.source_code)
            if validation.ok:
                return TranslateResponse(
                    ok=True,
                    source_code=compiled.source_code,
                    class_name=validation.class_name or compiled.class_name,
                    params_class_name=validation.params_class_name
                    or compiled.params_class_name,
                    suggested_strategy_name=req.strategy_name,
                    params_schema=validation.params_schema,
                    explanation=(
                        "Compiled directly from the builder graph — every "
                        "entry, exit, and risk node honoured."
                        + ("\n" + "\n".join(compiled.notes) if compiled.notes else "")
                    ),
                    risk_flag=compiled.risk_flag,
                )
            log.warning(
                "translate.compiled_invalid reason=%s errors=%s",
                compiled.reason,
                [e.as_dict() for e in validation.errors][:3],
            )
        else:
            log.info("translate.compile_fallback reason=%s", compiled.reason)
        # Either path: fall through to the LLM below.

    # Call the LLM with this user's own Anthropic key.
    await bind_request_ai_config(session, user.id)
    llm_result: TranslationResult = translate_nl_to_strategy(
        nl_description=req.nl_description,
        previous_source=req.previous_source,
        feedback=req.feedback,
    )

    if not llm_result.ok:
        return TranslateResponse(
            ok=False,
            llm_error=llm_result.error,
        )

    # Run the generated code through the validator (same path as direct submit)
    assert llm_result.source_code is not None
    validation: StrategyValidationResult = validate_strategy_source(
        llm_result.source_code
    )

    return TranslateResponse(
        ok=validation.ok,
        source_code=llm_result.source_code,
        class_name=validation.class_name or llm_result.class_name,
        params_class_name=validation.params_class_name or llm_result.params_class_name,
        suggested_strategy_name=llm_result.suggested_strategy_name,
        params_schema=validation.params_schema,
        explanation=llm_result.explanation,
        validation_errors=[e.as_dict() for e in validation.errors],
        risk_flag=llm_result.risk_flag,
        input_tokens=llm_result.input_tokens,
        output_tokens=llm_result.output_tokens,
    )


class PlanGraphRequest(BaseModel):
    prompt: str = Field(
        ..., min_length=2, max_length=4000,
        description="Plain-English strategy idea to turn into a builder node graph.",
    )
    asset_class: Optional[str] = Field(default=None, max_length=40)
    # The current canvas graph, sent so a follow-up message refines instead of
    # rebuilding from scratch. Shape: {"nodes":[...], "edges":[...]}.
    graph_json: Optional[dict[str, Any]] = Field(default=None)


class PlanGraphResponse(BaseModel):
    """An AI-built node graph in the frontend BuildResult shape.

    `ok=False` (with `error`) on any LLM failure — missing key, out of credits,
    timeout, no structured output. The frontend falls back to its offline
    heuristic builder in that case, so the chat never dead-ends.
    """
    ok: bool
    name: Optional[str] = None
    assetClass: Optional[str] = None
    plan: list[str] = []
    assumptions: list[str] = []
    questions: list[dict[str, Any]] = []
    graph: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0


@router.post("/plan-graph", response_model=PlanGraphResponse)
async def plan_graph_endpoint(
    req: PlanGraphRequest,
    user=Depends(get_current_user_record),
    session: AsyncSession = Depends(get_db_session),
) -> PlanGraphResponse:
    """AI builder: natural language → visual strategy node graph.

    This is what powers the studio "build assistant" chat. Unlike the old
    client-side keyword heuristic (which mapped anything to an RSI template),
    Claude reasons about the actual intent and places real palette nodes —
    including time-based / non-indicator strategies. The returned graph drops
    straight onto the React-Flow canvas and is compilable by /translate.
    """
    await bind_request_ai_config(session, user.id)
    result = plan_graph_from_nl(
        nl_description=req.prompt,
        asset_class_hint=req.asset_class,
        context_graph=req.graph_json,
    )
    d = result.to_dict()
    return PlanGraphResponse(
        ok=d["ok"],
        name=d["name"] or None,
        assetClass=d["assetClass"],
        plan=d["plan"],
        assumptions=d["assumptions"],
        questions=d["questions"],
        graph=d["graph"] if d["ok"] else None,
        error=d["error"],
        input_tokens=d["inputTokens"],
        output_tokens=d["outputTokens"],
    )


class PlanGraphFromCodeRequest(BaseModel):
    source_code: str = Field(
        ..., min_length=10, max_length=64_000,
        description="Python strategy source to render as a builder node graph.",
    )
    asset_class: Optional[str] = Field(default=None, max_length=40)


@router.post("/plan-graph-from-code", response_model=PlanGraphResponse)
async def plan_graph_from_code_endpoint(
    req: PlanGraphFromCodeRequest,
    user=Depends(get_current_user_record),
    session: AsyncSession = Depends(get_db_session),
) -> PlanGraphResponse:
    """AI: render the node graph that REPRESENTS a strategy's Python source.

    The reverse of /translate (graph -> code). Lets the builder show a visual
    view of a code-authored strategy. Best-effort: the Python source stays the
    source of truth, so the graph is a view (gaps land in `assumptions`).
    """
    await bind_request_ai_config(session, user.id)
    result = plan_graph_from_code(
        source_code=req.source_code,
        asset_class_hint=req.asset_class,
    )
    d = result.to_dict()
    return PlanGraphResponse(
        ok=d["ok"],
        name=d["name"] or None,
        assetClass=d["assetClass"],
        plan=d["plan"],
        assumptions=d["assumptions"],
        questions=d["questions"],
        graph=d["graph"] if d["ok"] else None,
        error=d["error"],
        input_tokens=d["inputTokens"],
        output_tokens=d["outputTokens"],
    )


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
        graph_json=row.get("graph_json"),
        asset_class=row.get("asset_class"),
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
        graph_json=row.get("graph_json"),
        asset_class=row.get("asset_class"),
        source_code=row["source_code"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
