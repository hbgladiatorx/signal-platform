"""Provider abstraction: config resolution + format adapters + agent loop.

The format adapters (Anthropic <-> OpenAI message/tool shapes) and the agentic
loop are the risky parts of the multi-provider work, so exercise them directly
with in-memory data (no network).
"""
from __future__ import annotations

import asyncio

import pytest

from packages.core import ai_client as C
from packages.core.ai_provider import (
    AIProviderConfig,
    build_config,
    platform_ai_enabled,
    set_request_ai_config,
)


# ---- provider config -------------------------------------------------------
def test_platform_ai_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_PLATFORM_AI", raising=False)
    assert platform_ai_enabled() is False


def test_build_config_openai_requires_model_and_base() -> None:
    cfg = build_config(provider="deepseek", api_key="sk-x")
    assert cfg is not None and cfg.is_openai
    assert cfg.base_url == "https://api.deepseek.com/v1"
    assert cfg.model == "deepseek-chat"  # preset default


def test_build_config_anthropic_leaves_model_empty() -> None:
    cfg = build_config(provider="anthropic", api_key="sk-x")
    assert cfg is not None and not cfg.is_openai
    assert cfg.model == ""  # per-feature default used at call time


def test_build_config_custom_without_model_is_none() -> None:
    # custom preset has no default model/base -> incomplete config rejected.
    assert build_config(provider="custom", api_key="sk-x") is None
    assert build_config(provider="custom", api_key="sk-x",
                        base_url="https://x/v1", model="m") is not None


def test_build_config_blank_key_is_none() -> None:
    assert build_config(provider="openai", api_key="  ") is None


# ---- tool + message adapters ----------------------------------------------
def test_to_openai_tools() -> None:
    anth = [{"name": "run", "description": "d", "input_schema": {"type": "object"}}]
    out = C._to_openai_tools(anth)
    assert out == [{
        "type": "function",
        "function": {"name": "run", "description": "d", "parameters": {"type": "object"}},
    }]


def test_openai_messages_shapes() -> None:
    turns = [
        C._Turn(role="user", text="hi"),
        C._Turn(role="assistant", text="", tool_calls=[C.ToolCall("id1", "run", {"a": 1})]),
        C._Turn(role="tool", tool_results=[{"id": "id1", "name": "run", "output": "ok"}]),
    ]
    msgs = C._openai_messages("SYS", turns)
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1] == {"role": "user", "content": "hi"}
    # assistant carries an OpenAI tool_calls array with JSON-string arguments
    assert msgs[2]["role"] == "assistant"
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "run"
    assert msgs[2]["tool_calls"][0]["function"]["arguments"] == '{"a": 1}'
    # tool result is its own role=tool message keyed by tool_call_id
    assert msgs[3] == {"role": "tool", "tool_call_id": "id1", "content": "ok"}


def test_anthropic_messages_shapes() -> None:
    turns = [
        C._Turn(role="assistant", text="t", tool_calls=[C.ToolCall("id1", "run", {"a": 1})]),
        C._Turn(role="tool", tool_results=[{"id": "id1", "name": "run", "output": "ok"}]),
    ]
    msgs = C._anthropic_messages(turns)
    blocks = msgs[0]["content"]
    assert {"type": "text", "text": "t"} in blocks
    assert any(b["type"] == "tool_use" and b["id"] == "id1" for b in blocks)
    assert msgs[1]["content"][0] == {
        "type": "tool_result", "tool_use_id": "id1", "content": "ok"
    }


# ---- agentic loop (backend mocked) ----------------------------------------
def test_agentic_loop_runs_tools_then_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    set_request_ai_config(AIProviderConfig("openai", "openai", "http://x/v1", "m", "sk"))

    # First model turn asks for a tool; second returns a final answer.
    scripted = [
        ("", [C.ToolCall("t1", "get_state", {"strategy_id": "S1"})], (1, 1)),
        ("all done", [], (1, 1)),
    ]

    def fake_complete(cfg, system, turns, tools, model, max_tokens):
        return scripted.pop(0)

    monkeypatch.setattr(C, "_complete", fake_complete)

    seen = {}

    async def dispatch(name, inp):
        seen["name"] = name
        return {"ok": True, "strategy_id": inp.get("strategy_id")}

    tracked = []

    res = asyncio.run(
        C.agentic_call(
            system="SYS", messages=[{"role": "user", "content": "go"}],
            tools=[], dispatch=dispatch, max_iters=5,
            on_tool=lambda tc, out: tracked.append(tc.name),
        )
    )
    assert res.finished is True
    assert res.reply == "all done"
    assert seen["name"] == "get_state"
    assert tracked == ["get_state"]
    assert len(res.tool_trace) == 1


def test_calls_fail_closed_without_config() -> None:
    set_request_ai_config(None)
    with pytest.raises(C.AIUnavailable):
        C.text_call(system="s", user="u")
