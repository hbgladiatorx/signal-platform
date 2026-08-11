"""The Bayn Copilot tool-use loop.

One turn = the user's message history in, the assistant's reply out, with any
number of tool calls executed server-side in between. The Anthropic SDK is
synchronous, so each model call is run in a threadpool while tool dispatch is
awaited normally on the request's DB session.

The loop also tracks the "current" strategy across tool calls so the caller can
re-render the pipeline stepper from a single, fresh state object — the same map
the chat chips and the agent's "what's next" line read.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from packages.core.anthropic_key import current_anthropic_key
from uuid import UUID

from anthropic import Anthropic, APIError, APITimeoutError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from packages.copilot.prompt import COPILOT_MODEL, MAX_TOOL_ITERATIONS, SYSTEM_PROMPT
from packages.copilot.state import compute_strategy_state
from packages.copilot.tools import TOOL_SCHEMAS, dispatch_tool
from packages.data.user_strategies import get_user_strategy

log = logging.getLogger(__name__)


class CopilotResult:
    def __init__(
        self,
        *,
        ok: bool,
        reply: str,
        strategy_id: Optional[str] = None,
        state: Optional[dict[str, Any]] = None,
        tool_trace: Optional[list[dict[str, Any]]] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: Optional[str] = None,
    ) -> None:
        self.ok = ok
        self.reply = reply
        self.strategy_id = strategy_id
        self.state = state
        self.tool_trace = tool_trace or []
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reply": self.reply,
            "strategy_id": self.strategy_id,
            "state": self.state,
            "tool_trace": self.tool_trace,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "error": self.error,
        }


def _blocks_to_serialisable(content: list[Any]) -> list[dict[str, Any]]:
    """Convert SDK response content blocks to plain dicts for the next request."""
    out: list[dict[str, Any]] = []
    for b in content:
        btype = getattr(b, "type", None)
        if btype == "text":
            out.append({"type": "text", "text": getattr(b, "text", "")})
        elif btype == "tool_use":
            out.append(
                {
                    "type": "tool_use",
                    "id": getattr(b, "id", ""),
                    "name": getattr(b, "name", ""),
                    "input": getattr(b, "input", {}) or {},
                }
            )
    return out


def _collect_text(content: list[Any]) -> str:
    parts = [getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text"]
    return "\n".join(p for p in parts if p).strip()


async def run_copilot_turn(
    *,
    session: AsyncSession,
    user: Any,
    registry: dict[str, Any],
    messages: list[dict[str, Any]],
    strategy_id: Optional[str] = None,
) -> CopilotResult:
    """Run one assistant turn over the supplied message history.

    `messages` is the running conversation in Anthropic format (the frontend
    owns history and sends it each turn). `strategy_id` seeds the "current"
    strategy for the closing state render; tool calls can change it.
    """
    api_key = current_anthropic_key()
    if not api_key:
        return CopilotResult(
            ok=False,
            reply=(
                "The copilot needs your Anthropic API key. Add one under "
                "**Settings → AI copilot key** — each user connects their own."
            ),
            error="missing_api_key",
        )

    client = Anthropic(api_key=api_key, timeout=90.0)
    convo = list(messages)
    tool_trace: list[dict[str, Any]] = []
    current_sid = strategy_id
    in_tokens = 0
    out_tokens = 0

    # Tell the agent which strategy is open on the canvas, so "this strategy"
    # (or an unqualified request) resolves without asking the user for an id.
    system = SYSTEM_PROMPT
    if strategy_id:
        system += (
            f"\n\nThe user currently has strategy {strategy_id} open on the "
            "canvas. When they say 'this strategy', 'it', or don't name one, "
            "act on this strategy_id. Still call get_strategy_state on it before "
            "acting."
        )

    def _call_llm() -> Any:
        return client.messages.create(
            model=os.environ.get("COPILOT_MODEL", COPILOT_MODEL),
            max_tokens=2048,
            system=system,
            tools=TOOL_SCHEMAS,
            messages=convo,
        )

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            resp = await run_in_threadpool(_call_llm)
        except APITimeoutError:
            return CopilotResult(
                ok=False, reply="That took too long — try again.", error="timeout",
                tool_trace=tool_trace, input_tokens=in_tokens, output_tokens=out_tokens,
            )
        except APIError as e:
            log.error("copilot.api_error err=%s", e)
            return CopilotResult(
                ok=False, reply=f"The assistant hit an API error: {type(e).__name__}.",
                error=str(e), tool_trace=tool_trace,
                input_tokens=in_tokens, output_tokens=out_tokens,
            )

        usage = getattr(resp, "usage", None)
        if usage:
            in_tokens += getattr(usage, "input_tokens", 0) or 0
            out_tokens += getattr(usage, "output_tokens", 0) or 0

        assistant_blocks = _blocks_to_serialisable(resp.content)
        convo.append({"role": "assistant", "content": assistant_blocks})

        tool_uses = [b for b in assistant_blocks if b["type"] == "tool_use"]
        if getattr(resp, "stop_reason", None) != "tool_use" or not tool_uses:
            # Final answer.
            reply = _collect_text(resp.content)
            state = await _final_state(session, user, current_sid)
            return CopilotResult(
                ok=True, reply=reply, strategy_id=current_sid, state=state,
                tool_trace=tool_trace, input_tokens=in_tokens, output_tokens=out_tokens,
            )

        # Execute every tool the model asked for, in order.
        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            tname = tu["name"]
            tinput = tu["input"]
            result = await dispatch_tool(
                tname, tinput, session=session, user=user, registry=registry
            )
            # Track the strategy in play for the closing state render.
            sid = tinput.get("strategy_id") or result.get("strategy_id")
            if sid:
                current_sid = str(sid)
            tool_trace.append({"name": tname, "input": tinput, "result": result})
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": _stringify(result),
                }
            )
        convo.append({"role": "user", "content": tool_results})

    # Ran out of iterations.
    state = await _final_state(session, user, current_sid)
    return CopilotResult(
        ok=True,
        reply="I worked through several steps but didn't finish — tell me how you'd like to proceed.",
        strategy_id=current_sid, state=state, tool_trace=tool_trace,
        input_tokens=in_tokens, output_tokens=out_tokens,
        error="max_iterations",
    )


def _stringify(result: dict[str, Any]) -> str:
    import json

    try:
        return json.dumps(result, default=str)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "unserialisable tool result"})


async def _final_state(
    session: AsyncSession, user: Any, strategy_id: Optional[str]
) -> Optional[dict[str, Any]]:
    if not strategy_id:
        return None
    try:
        sid = UUID(strategy_id)
    except (ValueError, TypeError):
        return None
    row = await get_user_strategy(session, strategy_id=sid, user_id=user.id)
    if row is None:
        return None
    return await compute_strategy_state(session, user_id=user.id, strategy_row=row)
