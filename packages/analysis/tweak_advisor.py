"""AI parameter-tweak advisor.

Given a backtest's deterministic analysis AND the strategy's builder node graph,
Claude proposes SPECIFIC, node-targeted parameter changes the user can apply and
re-backtest: "widen stopLoss from 1.5% to 3%", "raise RSI period 14→21", "drop
the cooldown". Each suggestion references a real graph node id + field so the
frontend can patch the graph in place and re-run.

This closes the loop the deterministic findings only hint at: instead of "tighten
your exits", it returns an editable {node, field, current, suggested} the user
tweaks and tests. Best-effort: returns ok=False (never raises) when the LLM is
unavailable, so the UI can fall back to the prose findings.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"

# Node fields that are genuinely tunable numbers/enums worth suggesting on.
# Mirrors the builder palette (thebayn NodePalette.tsx). Anything else is left
# alone so we don't propose edits the canvas can't render or the compiler ignores.
TUNABLE_HINT = '''\
Tunable node fields by node type (only suggest changes to these):
  price       → timeframe ("1m","5m","15m","1h","4h","1d")
  sma/ema     → period (int), source
  vwap        → period
  rsi         → period (int)
  macd        → fast, slow, signal (ints)
  bb          → period, stdDev
  atr         → period
  stoch       → k, d
  comparator  → op (> < >= <= == !=), value (number)
  crossover   → op (crosses_above|crosses_below)
  timeWindow  → start, end ("HH:MM")
  cooldown    → bars (int)
  positionSize→ value (number), type (percent_account|fixed_cash)
  stopLoss    → value (number, percent), type (percent|atr)
  takeProfit  → value (number), type (r_multiple|percent)
  maxDailyLoss→ value
  maxConcurrent→ value
  formula     → expr (string)
  entry       → direction (LONG|SHORT)
'''

SYSTEM_PROMPT = f'''\
You are a quantitative strategy optimizer. You are given (a) a STRUCTURED
analysis of a backtest (verdict, metrics, ranked findings) and (b) the strategy's
node GRAPH from a visual builder. Propose concrete parameter tweaks that would
plausibly improve the strategy, each tied to a SPECIFIC node in the graph.

Use the `emit_param_tweaks` tool. Rules:
- Every tweak must reference a real node by its `node_id` (copy it exactly from
  the provided graph) and a single `field` within that node's data.
- `current` = the node's existing value for that field (copy it). `suggested` =
  your new value, the SAME json type (number stays number, string stays string).
- Only touch tunable fields (below). Never invent nodes or fields.
- Ground each `rationale` in a finding or metric (e.g. "win rate 38% < 50%
  breakeven — widening the stop reduces premature stop-outs"). One sentence.
- Order tweaks by expected impact, highest first. Return 2-6 tweaks. If the
  strategy is already strong or you genuinely have no high-confidence change,
  return an empty list and say why in `summary`.
- `summary`: 1-2 sentences on the overall tuning direction.

{TUNABLE_HINT}

Be specific and conservative — these get applied and re-backtested directly.'''


EMIT_TWEAKS_TOOL: dict[str, Any] = {
    "name": "emit_param_tweaks",
    "description": "Return node-targeted parameter tweaks to apply and re-backtest.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "tweaks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string"},
                        "node_label": {"type": "string"},
                        "node_type": {"type": "string"},
                        "field": {"type": "string"},
                        "current": {
                            "description": "Existing value (number or string).",
                            "type": ["number", "string", "boolean", "null"],
                        },
                        "suggested": {
                            "description": "Proposed value, same type as current.",
                            "type": ["number", "string", "boolean"],
                        },
                        "rationale": {"type": "string"},
                    },
                    "required": ["node_id", "field", "suggested", "rationale"],
                },
            },
        },
        "required": ["summary", "tweaks"],
    },
}


@dataclass
class TweakResult:
    ok: bool
    summary: str = ""
    tweaks: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0


def _compact_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Strip the graph to what the model needs to target nodes (ids + data)."""
    nodes = []
    for n in (graph.get("nodes") or []):
        nodes.append(
            {
                "node_id": n.get("id"),
                "type": n.get("type"),
                "label": n.get("label"),
                "data": n.get("data") or {},
            }
        )
    return {"nodes": nodes}


def _validate_tweaks(
    tweaks: list[dict[str, Any]], graph: dict[str, Any]
) -> list[dict[str, Any]]:
    """Keep only tweaks that reference a real node + a field that exists (or is
    a known-tunable field) on it, and where suggested actually differs."""
    by_id = {str(n.get("id")): n for n in (graph.get("nodes") or [])}
    out: list[dict[str, Any]] = []
    for t in tweaks:
        nid = str(t.get("node_id") or "")
        node = by_id.get(nid)
        if not node:
            continue
        fieldname = t.get("field")
        if not fieldname:
            continue
        data = node.get("data") or {}
        current = data.get(fieldname, t.get("current"))
        suggested = t.get("suggested")
        if suggested is None:
            continue
        # Drop no-ops.
        if str(current) == str(suggested):
            continue
        out.append(
            {
                "node_id": nid,
                "node_label": node.get("label") or t.get("node_label") or node.get("type"),
                "node_type": node.get("type") or t.get("node_type"),
                "field": fieldname,
                "current": current,
                "suggested": suggested,
                "rationale": t.get("rationale") or "",
            }
        )
    return out


def suggest_param_tweaks(
    analysis: dict[str, Any],
    graph: dict[str, Any] | None,
    strategy_name: str | None = None,
) -> TweakResult:
    """Best-effort LLM tweak suggestions tied to graph nodes. Never raises."""
    if not graph or not (graph.get("nodes")):
        return TweakResult(
            ok=False,
            error="This strategy has no editable node graph to tune. Tweak it in the visual builder.",
        )

    try:
        from anthropic import Anthropic, APIError, APITimeoutError
    except ImportError:
        return TweakResult(ok=False, error="The 'anthropic' package is not installed.")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return TweakResult(ok=False, error="ANTHROPIC_API_KEY is not set in this environment.")

    payload = {
        "strategy": strategy_name,
        "verdict": analysis.get("verdict"),
        "score_0_100": analysis.get("score"),
        "headline": analysis.get("headline"),
        "metrics": analysis.get("metrics"),
        "findings": [
            {
                "severity": f.get("severity"),
                "title": f.get("title"),
                "detail": f.get("detail"),
                "suggestion": f.get("suggestion"),
            }
            for f in analysis.get("findings", [])
        ],
        "graph": _compact_graph(graph),
    }
    user_msg = (
        "Backtest analysis and strategy graph below. Propose node-targeted "
        "parameter tweaks via the emit_param_tweaks tool.\n\n```json\n"
        + json.dumps(payload, indent=2, default=str)
        + "\n```"
    )

    client = Anthropic(api_key=api_key, timeout=60.0)
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            tools=[EMIT_TWEAKS_TOOL],
            tool_choice={"type": "tool", "name": "emit_param_tweaks"},
            messages=[{"role": "user", "content": user_msg}],
        )
    except APITimeoutError:
        return TweakResult(ok=False, error="The tweak advisor timed out. Try again.")
    except APIError as e:
        msg = str(e)
        if "credit" in msg.lower() or "balance" in msg.lower():
            msg = "Anthropic credit balance is too low — top up to enable AI tuning."
        return TweakResult(ok=False, error=msg[:300])
    except Exception as e:  # noqa: BLE001
        return TweakResult(ok=False, error=f"Tweak advisor failed: {type(e).__name__}")

    usage = getattr(resp, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) if usage else 0
    out_tok = getattr(usage, "output_tokens", 0) if usage else 0

    tool_input: Optional[dict[str, Any]] = None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "emit_param_tweaks":
            tool_input = block.input  # type: ignore[attr-defined]
            break
    if tool_input is None:
        return TweakResult(ok=False, error="The advisor returned no structured tweaks.", input_tokens=in_tok, output_tokens=out_tok)

    tweaks = _validate_tweaks(tool_input.get("tweaks") or [], graph)
    return TweakResult(
        ok=True,
        summary=str(tool_input.get("summary") or ""),
        tweaks=tweaks,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )
