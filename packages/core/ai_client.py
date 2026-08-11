"""Provider-agnostic LLM client.

One interface, two backends:
  * "anthropic" — the native Anthropic SDK (unchanged behaviour, the default).
  * "openai"    — any OpenAI-compatible endpoint (OpenAI, DeepSeek, Groq,
                  OpenRouter, or a custom base URL), via the `openai` SDK.

Three primitives cover every AI feature:
  * text_call        — plain-text completion (backtest narration).
  * structured_call  — force ONE tool and return its parsed JSON args
                       (strategy translation, graph planning, tweak advice).
  * agentic_call     — the multi-tool agent loop (the copilot).

The active provider comes from the request-bound config (ai_provider). All calls
FAIL CLOSED: no config -> AIUnavailable, which callers turn into a friendly
"connect your AI provider" message.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from packages.core.ai_provider import AIProviderConfig, current_ai_config


class AIUnavailable(Exception):
    """No provider/key is configured for the current request."""


class AIError(Exception):
    """The provider returned an error (auth, rate limit, timeout, etc.)."""


# ============================================================
# Neutral conversation model (backend-agnostic)
# ============================================================
@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class _Turn:
    role: str  # "user" | "assistant" | "tool"
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)  # {id,name,output}


@dataclass
class AgenticResult:
    reply: str
    tool_trace: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int
    finished: bool  # False if it hit the iteration cap


def _require_config() -> AIProviderConfig:
    cfg = current_ai_config()
    if cfg is None:
        raise AIUnavailable(
            "Connect an AI provider under Settings → AI copilot to use this."
        )
    return cfg


def _model(cfg: AIProviderConfig, default_model: str | None) -> str:
    # Anthropic keeps per-feature defaults unless the user pinned a model.
    return cfg.model or default_model or ""


def _stringify(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, default=str)


# ============================================================
# Tool-schema conversion
# ============================================================
def _to_openai_tools(anthropic_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic tool schema -> OpenAI function-tool schema."""
    out = []
    for t in anthropic_tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
        )
    return out


# ============================================================
# Anthropic backend
# ============================================================
def _anthropic_client(cfg: AIProviderConfig, timeout: float):
    from anthropic import Anthropic

    return Anthropic(api_key=cfg.api_key, timeout=timeout)


def _anthropic_messages(turns: list[_Turn]) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    for t in turns:
        if t.role == "user":
            msgs.append({"role": "user", "content": t.text})
        elif t.role == "assistant":
            content: list[dict[str, Any]] = []
            if t.text:
                content.append({"type": "text", "text": t.text})
            for tc in t.tool_calls:
                content.append(
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
                )
            msgs.append({"role": "assistant", "content": content})
        elif t.role == "tool":
            msgs.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": r["id"], "content": r["output"]}
                        for r in t.tool_results
                    ],
                }
            )
    return msgs


def _anthropic_complete(
    cfg: AIProviderConfig, system: str, turns: list[_Turn],
    tools: list[dict[str, Any]], model: str, max_tokens: int,
) -> tuple[str, list[ToolCall], tuple[int, int]]:
    from anthropic import APIError, APITimeoutError

    client = _anthropic_client(cfg, 90.0)
    try:
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            tools=tools, messages=_anthropic_messages(turns),
        )
    except APITimeoutError as e:  # noqa: F841
        raise AIError("The model timed out. Try again.")
    except APIError as e:
        raise AIError(f"{type(e).__name__}: {getattr(e, 'message', str(e))}"[:300])

    text_out, calls = "", []
    for b in resp.content:
        if getattr(b, "type", None) == "text":
            text_out += getattr(b, "text", "")
        elif getattr(b, "type", None) == "tool_use":
            calls.append(ToolCall(id=b.id, name=b.name, input=dict(b.input or {})))
    usage = getattr(resp, "usage", None)
    return text_out, calls, (
        getattr(usage, "input_tokens", 0) or 0,
        getattr(usage, "output_tokens", 0) or 0,
    )


# ============================================================
# OpenAI-compatible backend
# ============================================================
def _openai_client(cfg: AIProviderConfig, timeout: float):
    from openai import OpenAI

    return OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=timeout)


def _openai_messages(system: str, turns: list[_Turn]) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for t in turns:
        if t.role == "user":
            msgs.append({"role": "user", "content": t.text})
        elif t.role == "assistant":
            m: dict[str, Any] = {"role": "assistant", "content": t.text or None}
            if t.tool_calls:
                m["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.input)},
                    }
                    for tc in t.tool_calls
                ]
            msgs.append(m)
        elif t.role == "tool":
            for r in t.tool_results:
                msgs.append(
                    {"role": "tool", "tool_call_id": r["id"], "content": r["output"]}
                )
    return msgs


def _openai_complete(
    cfg: AIProviderConfig, system: str, turns: list[_Turn],
    tools: list[dict[str, Any]], model: str, max_tokens: int,
) -> tuple[str, list[ToolCall], tuple[int, int]]:
    from openai import APIError, APITimeoutError

    client = _openai_client(cfg, 90.0)
    try:
        resp = client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            messages=_openai_messages(system, turns),
            tools=_to_openai_tools(tools) if tools else None,
        )
    except APITimeoutError:
        raise AIError("The model timed out. Try again.")
    except APIError as e:
        raise AIError(f"{type(e).__name__}: {getattr(e, 'message', str(e))}"[:300])

    choice = resp.choices[0].message
    text_out = choice.content or ""
    calls: list[ToolCall] = []
    for tc in getattr(choice, "tool_calls", None) or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(id=tc.id, name=tc.function.name, input=args))
    usage = getattr(resp, "usage", None)
    return text_out, calls, (
        getattr(usage, "prompt_tokens", 0) or 0,
        getattr(usage, "completion_tokens", 0) or 0,
    )


def _complete(
    cfg: AIProviderConfig, system: str, turns: list[_Turn],
    tools: list[dict[str, Any]], model: str, max_tokens: int,
) -> tuple[str, list[ToolCall], tuple[int, int]]:
    fn = _openai_complete if cfg.is_openai else _anthropic_complete
    return fn(cfg, system, turns, tools, model, max_tokens)


# ============================================================
# Public primitives
# ============================================================
def text_call(
    *, system: str, user: str, default_model: str | None = None, max_tokens: int = 900
) -> str:
    """Plain-text completion. Raises AIUnavailable / AIError."""
    cfg = _require_config()
    turns = [_Turn(role="user", text=user)]
    text_out, _calls, _usage = _complete(
        cfg, system, turns, [], _model(cfg, default_model), max_tokens
    )
    return text_out.strip()


def structured_call(
    *, system: str, user: str, tool_name: str, tool_description: str,
    input_schema: dict[str, Any], default_model: str | None = None, max_tokens: int = 4096,
) -> dict[str, Any]:
    """Force ONE tool and return its parsed JSON arguments. Raises on failure."""
    cfg = _require_config()
    tool = {"name": tool_name, "description": tool_description, "input_schema": input_schema}
    model = _model(cfg, default_model)

    if cfg.is_openai:
        from openai import APIError, APITimeoutError

        client = _openai_client(cfg, 60.0)
        try:
            resp = client.chat.completions.create(
                model=model, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                tools=_to_openai_tools([tool]),
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
        except APITimeoutError:
            raise AIError("The model timed out. Try again.")
        except APIError as e:
            raise AIError(f"{type(e).__name__}: {getattr(e, 'message', str(e))}"[:300])
        tcs = getattr(resp.choices[0].message, "tool_calls", None) or []
        if not tcs:
            raise AIError("The model did not return the expected structured output.")
        try:
            return json.loads(tcs[0].function.arguments or "{}")
        except json.JSONDecodeError:
            raise AIError("The model returned malformed structured output.")

    # Anthropic
    from anthropic import APIError, APITimeoutError

    client = _anthropic_client(cfg, 60.0)
    try:
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            tools=[tool], tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user}],
        )
    except APITimeoutError:
        raise AIError("The model timed out. Try again.")
    except APIError as e:
        raise AIError(f"{type(e).__name__}: {getattr(e, 'message', str(e))}"[:300])
    for b in resp.content:
        if getattr(b, "type", None) == "tool_use" and b.name == tool_name:
            return dict(b.input or {})
    raise AIError("The model did not return the expected structured output.")


async def agentic_call(
    *,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    dispatch: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    default_model: str | None = None,
    max_iters: int = 8,
    max_tokens: int = 2048,
    on_tool: Callable[[ToolCall, dict[str, Any]], None] | None = None,
) -> AgenticResult:
    """Run the multi-tool agent loop. `dispatch(name, input)` executes a tool and
    returns its result dict; `on_tool` is called after each for side-tracking."""
    cfg = _require_config()
    model = _model(cfg, default_model)
    turns: list[_Turn] = [
        _Turn(role=("assistant" if m.get("role") == "assistant" else "user"),
              text=m["content"] if isinstance(m.get("content"), str) else _stringify(m.get("content")))
        for m in messages
    ]
    trace: list[dict[str, Any]] = []
    in_tok = out_tok = 0

    for _ in range(max_iters):
        text_out, tool_calls, (i, o) = await asyncio.to_thread(
            _complete, cfg, system, turns, tools, model, max_tokens
        )
        in_tok += i
        out_tok += o
        if not tool_calls:
            return AgenticResult(text_out, trace, in_tok, out_tok, finished=True)

        turns.append(_Turn(role="assistant", text=text_out, tool_calls=tool_calls))
        results: list[dict[str, Any]] = []
        for tc in tool_calls:
            out = await dispatch(tc.name, tc.input)
            if on_tool is not None:
                on_tool(tc, out)
            trace.append({"name": tc.name, "input": tc.input, "result": out})
            results.append({"id": tc.id, "name": tc.name, "output": _stringify(out)})
        turns.append(_Turn(role="tool", tool_results=results))

    return AgenticResult(
        "I worked through several steps but didn't finish — tell me how you'd like to proceed.",
        trace, in_tok, out_tok, finished=False,
    )
