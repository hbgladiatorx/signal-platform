"""Bayn Copilot API — the single chat box that drives the whole lifecycle.

Endpoints (JWT-protected, user-scoped):
  POST /copilot/chat                       run one assistant turn (tool-use loop)
  GET  /copilot/strategies/{id}/state      the lifecycle state for the stepper/chips

The chat endpoint runs the agent loop server-side: it calls Claude with the
copilot tool set, executes each tool against the real platform (build, backtest,
OOS, forward, promote, deploy, submit), and returns the assistant's reply plus a
fresh `state` object so the UI re-renders the pipeline stepper in lock-step.

History is owned by the frontend: send the full `messages` array each turn.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from packages.copilot.agent import run_copilot_turn
from packages.copilot.state import compute_strategy_state
from packages.data.user_strategies import (
    get_user_strategy,
    set_strategy_lifecycle_milestone,
)
from services.api.deps import (
    CurrentUserRecord,
    get_current_user_record,
    get_db_session,
)
from services.api.routers.strategies import get_strategy_registry

router = APIRouter(prefix="/copilot", tags=["copilot"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    # Either a plain string (the common case from the UI) or the structured
    # Anthropic content-block list for replayed tool turns.
    content: Any


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=100)
    # The strategy currently open on the canvas, if any. Seeds the closing
    # state render; tool calls may change it (e.g. build_strategy).
    strategy_id: UUID | None = None


class ChatResponse(BaseModel):
    ok: bool
    reply: str
    strategy_id: str | None = None
    state: dict[str, Any] | None = None
    tool_trace: list[dict[str, Any]] = []
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    req: ChatRequest,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> ChatResponse:
    if req.messages[-1].role != "user":
        raise HTTPException(422, "The last message must be from the user.")

    result = await run_copilot_turn(
        session=session,
        user=user,
        registry=get_strategy_registry(),
        messages=[{"role": m.role, "content": m.content} for m in req.messages],
        strategy_id=str(req.strategy_id) if req.strategy_id else None,
    )
    return ChatResponse(**result.to_dict())


@router.get("/strategies/{strategy_id}/state", response_model=dict)
async def strategy_state_endpoint(
    strategy_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> dict[str, Any]:
    """The aggregator the spec calls get_strategy_state — also the source of
    truth for the pipeline stepper and the suggested-action chips."""
    row = await get_user_strategy(session, strategy_id=strategy_id, user_id=user.id)
    if row is None:
        raise HTTPException(404, "Strategy not found")
    return await compute_strategy_state(session, user_id=user.id, strategy_row=row)


class SkipForwardTestResponse(BaseModel):
    ok: bool
    forward_test: str = Field(..., description='"skipped" — recorded, never "passed".')
    state: dict[str, Any]


@router.post("/strategies/{strategy_id}/skip-forward-test", response_model=SkipForwardTestResponse)
async def skip_forward_test_endpoint(
    strategy_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> SkipForwardTestResponse:
    """Explicitly advance a VALIDATED strategy toward deployable WITHOUT forward
    testing — an honest, recorded opt-out, not a silent bypass.

    Requires the strategy to have passed OOS first (you can't skip a stage you
    haven't reached). Records `forward_test_skipped_at` and promotes to
    deployable. The state then reports forward_test="skipped" with
    forward_started=false — it is never recorded as if forward testing passed.
    Forward testing remains the default path; this is the user's deliberate skip.
    """
    row = await get_user_strategy(session, strategy_id=strategy_id, user_id=user.id)
    if row is None:
        raise HTTPException(404, "Strategy not found")

    state = await compute_strategy_state(session, user_id=user.id, strategy_row=row)
    if not state["gates_passed"].get("oos_passed"):
        raise HTTPException(
            status_code=422,
            detail={"msg": "Validate the strategy out-of-sample (run OOS) before "
                           "skipping forward testing.",
                    "stage": state["stage"]},
        )
    if state["gates_passed"].get("forward_started"):
        raise HTTPException(
            status_code=409,
            detail={"msg": "Forward testing has already started for this strategy; "
                           "there's nothing to skip."},
        )

    await set_strategy_lifecycle_milestone(
        session, strategy_id=strategy_id, user_id=user.id,
        forward_skipped=True, promoted=True,
    )
    await session.commit()

    fresh = await get_user_strategy(session, strategy_id=strategy_id, user_id=user.id)
    new_state = await compute_strategy_state(session, user_id=user.id, strategy_row=fresh)
    return SkipForwardTestResponse(ok=True, forward_test=new_state["forward_test"], state=new_state)
