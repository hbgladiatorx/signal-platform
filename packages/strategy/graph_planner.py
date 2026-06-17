"""
LLM-based natural language → visual strategy GRAPH planner.

This is the AI behind the studio "build assistant" chat. Given a plain-English
description ("enter btc, hold one minute, then sell, wait a minute, repeat"),
Claude reasons about the actual intent and emits a node graph in the EXACT
shape the React-Flow builder canvas renders — data → indicator → logic → risk →
signal nodes wired by edges.

This deliberately does NOT pattern-match keywords (the old client-side
`buildGraphFromPrompt` did, which is why "hold one minute then sell" came back
as an RSI strategy). The model places only nodes from the canvas palette, so
every node it emits is editable in the inspector and compilable by
`graph_compiler.compile_graph_to_source` for a real backtest.

Output contract (returned to the frontend as a `BuildResult`):
  { ok, name, assetClass, plan[], assumptions[], questions[], graph:{nodes,edges} }
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

# claude-sonnet-4-6 is the current Sonnet model; claude-sonnet-4-20250514 was
# retired and now 404s. Override via GRAPH_PLANNER_MODEL if needed.
MODEL = os.environ.get("GRAPH_PLANNER_MODEL", "claude-sonnet-4-6")

# ============================================================
# The canvas node palette — the ONLY node types the AI may emit.
# Mirrors thebayn src/components/studio/NodePalette.tsx::PALETTE.
# Keep these two in sync; an unknown type still renders but is not
# inspector-editable and the graph compiler may not understand it.
# ============================================================
PALETTE_DOC = '''\
DATA (category "data") — every graph starts here:
  price        data: {symbol, timeframe}   e.g. {"symbol":"BTC-USDT@BINANCEUS","timeframe":"1m"}
  volume       data: {}
  orderBook    data: {depth}               crypto only
  optionsChain data: {symbol}              options only
  fundamentals data: {}                    stocks only
  econCalendar data: {}

INDICATOR (category "indicator") — transforms a feed into a number:
  sma     data: {period, source}
  ema     data: {period, source}
  vwap    data: {period}
  rsi     data: {period}
  macd    data: {fast, slow, signal}
  bb      data: {period, stdDev}
  atr     data: {period}
  stoch   data: {k, d}
  formula data: {expr}     arbitrary expression, e.g. {"expr":"bars_in_trade >= 1"}

LOGIC (category "logic") — combines values into a true/false trigger:
  comparator data: {op, value}     op one of > < >= <= == !=
  crossover  data: {op}            op "crosses_above" | "crosses_below"
  and        data: {}
  or         data: {}
  not        data: {}
  timeWindow data: {start, end}    intraday clock window, e.g. {"start":"09:30","end":"15:45"}
  cooldown   data: {bars}          wait N bars after a trade before re-entering

RISK (category "risk"):
  positionSize data: {type, value}   type "percent_account" | "fixed_cash"
  stopLoss     data: {type, value}   type "percent" | "atr"
  takeProfit   data: {type, value}   type "r_multiple" | "percent"
  maxDailyLoss data: {value}
  maxConcurrent data: {value}

SIGNAL (category "signal") — the terminal node(s) that fire the trade:
  entry data: {direction}   direction "LONG" | "SHORT"
  exit  data: {}            close the open position
  alert data: {message}
'''

SYSTEM_PROMPT = f'''\
You are the build assistant for the Signal Platform's visual strategy builder.
A user describes a trading idea in plain English. You translate it into a NODE
GRAPH that renders on a React-Flow canvas, then gets compiled and backtested.

You MUST call the `emit_strategy_graph` tool. Reason about what the user ACTUALLY
asked for — do not force every idea into an RSI/indicator mold. Many valid
strategies are time-based, price-action, or scheduling rules with no classical
indicator at all.

# THE NODE PALETTE — emit ONLY these node types

{PALETTE_DOC}

# GRAPH RULES

1. Flow left-to-right through the five categories: data → indicator → logic →
   risk → signal. Not every category is required, but EVERY graph needs at
   least one `data` node (usually `price`) and at least one `signal` node
   (usually `entry`).
2. Wire it with edges. An edge {{source, target}} means the source feeds the
   target. Indicators read from a data node; logic reads from indicators or
   data; the entry/exit signal reads from the logic node(s) AND from any risk
   nodes (stopLoss, positionSize, takeProfit) that govern it.
3. Give every node a short human label (e.g. "Price · BTC-PERP 1m", "RSI(14)",
   "Hold 1 bar", "Entry LONG").
4. Pick the symbol and timeframe from the request. Use REAL platform symbols so
   the strategy has market data to backtest:
   - Crypto = "<BASE>-USDT@BINANCEUS" (USDT pairs have the deepest history),
     e.g. BTC-USDT@BINANCEUS, ETH-USDT@BINANCEUS, SOL-USDT@BINANCEUS. Do NOT use
     "-PERP" or bare "BTC" — those are not real instruments.
   - Stocks/options = "<TICKER>@ALPACA", e.g. SPY@ALPACA, AAPL@ALPACA, AMD@ALPACA.
   Set assetClass to one of: crypto, stocks, options, futures.
5. TIME-BASED / NON-INDICATOR ideas: express durations with the timeframe plus
   logic nodes — there is no "indicator" requirement.
   - "hold for one minute" on a 1m chart = exit one bar after entry. Model the
     exit trigger with a `formula` node like {{"expr":"bars_in_trade >= 1"}}
     feeding an `exit` signal, OR a `takeProfit`/`stopLoss` if they gave levels.
   - "wait one minute before re-entering" = a `cooldown` node {{"bars":1}} feeding
     the entry signal.
   - "every day at 9:30" = a `timeWindow` node.
   Do NOT invent an RSI or moving average the user never mentioned.
6. If the idea is genuinely just an indicator rule ("buy SPY when RSI < 30"),
   build that faithfully with the right indicator + comparator.

# OUTPUT FIELDS

- name: a short strategy name derived from the idea (e.g. "BTC 1-Minute Scalp Cycle").
- assetClass: crypto | stocks | options | futures.
- plan: 3-6 short present-tense bullet lines describing what the graph does, in
  order. Each must reflect the ACTUAL nodes you emitted.
- assumptions: anything you had to infer (timeframe, symbol, missing exit/stop).
  Be honest; if they gave no stop, say you defaulted one or left it off.
- questions: 0-3 clarifying questions, each with 2-3 plain-English answer options
  phrased as instructions (e.g. {{"q":"Which symbol?","options":["Use BTC-PERP","Use ETH-PERP"]}}).
  Only ask about things that genuinely change the strategy.
- nodes: each {{id, type, category, label, data, x, y}}. Use distinct ids
  ("price-1","entry-1", …). Lay them out left-to-right: data x≈40, indicator
  x≈300, logic x≈560, risk x≈800, signal x≈1060; stack siblings ~120px apart in y.
- edges: each {{source, target}} referencing node ids.

Be precise and faithful to the user's words.'''


EMIT_GRAPH_TOOL: dict[str, Any] = {
    "name": "emit_strategy_graph",
    "description": "Return the strategy as a renderable node graph for the builder canvas.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "assetClass": {
                "type": "string",
                "enum": ["crypto", "stocks", "options", "futures"],
            },
            "plan": {"type": "array", "items": {"type": "string"}},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "q": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["q", "options"],
                },
            },
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ["data", "indicator", "logic", "risk", "signal"],
                        },
                        "label": {"type": "string"},
                        "data": {"type": "object"},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                    },
                    "required": ["id", "type", "category", "label"],
                },
            },
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                    },
                    "required": ["source", "target"],
                },
            },
        },
        "required": ["name", "assetClass", "plan", "nodes", "edges"],
    },
}

# Column x-positions used to auto-lay-out any node the model leaves unplaced.
_CATEGORY_X = {"data": 40, "indicator": 300, "logic": 560, "risk": 800, "signal": 1060}


@dataclass
class GraphPlan:
    ok: bool
    name: str = ""
    asset_class: str = "crypto"
    plan: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        # Shaped to the frontend BuildResult contract (graph nested, camelCase).
        return {
            "ok": self.ok,
            "name": self.name,
            "assetClass": self.asset_class,
            "plan": self.plan,
            "assumptions": self.assumptions,
            "questions": self.questions,
            "graph": {"nodes": self.nodes, "edges": self.edges},
            "error": self.error,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
        }


def _normalize_nodes_edges(
    raw_nodes: list[dict[str, Any]], raw_edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Coerce the model's nodes/edges into the canvas StrategyNode/Edge shape.

    - Guarantee each node has an id, position {x,y}, and a data object.
    - Auto-place nodes the model left unpositioned by category column, stacking
      siblings vertically so the layout never overlaps into an unreadable pile.
    - Give every edge a stable id and drop edges that reference missing nodes.
    """
    nodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    per_col_count: dict[str, int] = {}

    for i, rn in enumerate(raw_nodes or []):
        nid = str(rn.get("id") or f"n-{i}")
        if nid in seen_ids:
            nid = f"{nid}-{i}"
        seen_ids.add(nid)
        category = rn.get("category") or "data"
        # Auto-layout fallback when the model omitted coordinates.
        x = rn.get("x")
        y = rn.get("y")
        if x is None or y is None:
            col = per_col_count.get(category, 0)
            per_col_count[category] = col + 1
            x = _CATEGORY_X.get(category, 300)
            y = 60 + col * 120
        data = rn.get("data")
        if not isinstance(data, dict):
            data = {}
        nodes.append(
            {
                "id": nid,
                "type": rn.get("type") or "formula",
                "category": category,
                "label": rn.get("label") or rn.get("type") or "Node",
                "position": {"x": x, "y": y},
                "data": data,
            }
        )

    valid_ids = {n["id"] for n in nodes}
    edges: list[dict[str, Any]] = []
    for j, re_ in enumerate(raw_edges or []):
        src = str(re_.get("source") or "")
        tgt = str(re_.get("target") or "")
        if src in valid_ids and tgt in valid_ids:
            edges.append({"id": f"e-{j}-{src}-{tgt}", "source": src, "target": tgt})

    return nodes, edges


# System prompt for the reverse direction: read Python strategy source and
# render the equivalent builder node graph. Reuses the same palette + tool so
# the output is a normal, inspector-editable graph. This is a best-effort VIEW
# of the code — the Python source remains the source of truth.
CODE_SYSTEM_PROMPT = f'''\
You are the build assistant for the Signal Platform's visual strategy builder.
You are given the PYTHON SOURCE of a trading strategy (a Strategy subclass with
an on_bar method). Your job is to render the node GRAPH that best REPRESENTS
that code on the React-Flow builder canvas, so the user can see their code as a
diagram.

You MUST call the `emit_strategy_graph` tool. Read the actual code: the
indicators it computes (ctx.rsi/sma/ema/macd/etc. and their periods), the
entry/exit conditions (comparisons, crossovers, regime filters), the position
sizing, and any stop-loss / take-profit. Emit nodes that mirror those exactly —
do NOT invent indicators or conditions the code does not contain, and do NOT
drop ones it does.

# THE NODE PALETTE — emit ONLY these node types

{PALETTE_DOC}

# RULES

1. Flow left-to-right: data -> indicator -> logic -> risk -> signal. Every graph
   needs at least one `data` node and at least one `signal` node.
2. Map the code faithfully:
   - ctx.rsi(sym, N) -> rsi node {{period:N}}; ctx.sma(sym, N) -> sma {{period:N}}; etc.
   - `rsi < 43` -> comparator {{op:"<", value:43}}; `price > sma` (regime filter)
     -> comparator on price vs the sma feed.
   - take_profit_pct -> takeProfit {{type:"percent", value:...}}; stop_loss_pct
     -> stopLoss {{type:"percent", value:...}}.
   - submit_buy_market -> entry {{direction:"LONG"}}; a short side -> entry {{direction:"SHORT"}}.
   - position_pct -> positionSize {{type:"percent_account", value:...}}.
   Use the symbol/timeframe from the code if present, else a sensible default
   (crypto "<BASE>-USDT@BINANCEUS").
3. If a piece of the code's logic cannot be expressed in the palette (e.g. a
   custom regime gate or true short side), approximate it with the closest nodes
   and NOTE it in `assumptions` — the graph is a view, the code is authoritative.
4. Give every node a short label and lay them out left-to-right by category.

# OUTPUT FIELDS

- name: keep the strategy's existing name/docstring title if discernible.
- assetClass: crypto | stocks | options | futures (infer from the symbol).
- plan: 3-6 present-tense bullets describing what the code does, in order.
- assumptions: anything the palette could not represent exactly (be honest).
- questions: leave empty ([]) — you are rendering existing code, not gathering requirements.
- nodes / edges: as in the tool schema, laid out left-to-right.

Be faithful to the code.'''


def _run_emit(
    system_prompt: str, user_msg: str, asset_class_hint: Optional[str]
) -> GraphPlan:
    """Shared Claude call + parse for both NL->graph and code->graph planners.

    Returns GraphPlan(ok=False, error=...) on any failure (missing key, out of
    credits, timeout, no tool_use) so the frontend can degrade gracefully
    instead of throwing.
    """
    try:
        from anthropic import Anthropic, APIError, APITimeoutError
    except ImportError:
        return GraphPlan(
            ok=False,
            error="The 'anthropic' package is not installed in the api container.",
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return GraphPlan(
            ok=False,
            error="ANTHROPIC_API_KEY is not set in the api container's environment.",
        )

    client = Anthropic(api_key=api_key, timeout=60.0)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=[EMIT_GRAPH_TOOL],
            tool_choice={"type": "tool", "name": "emit_strategy_graph"},
            messages=[{"role": "user", "content": user_msg}],
        )
    except APITimeoutError:
        return GraphPlan(ok=False, error="The AI builder timed out. Try again.")
    except APIError as exc:  # includes auth + credit-balance errors
        msg = str(getattr(exc, "message", "") or exc)
        return GraphPlan(ok=False, error=f"Anthropic API error: {msg[:300]}")
    except Exception as exc:  # noqa: BLE001 — never crash the endpoint
        return GraphPlan(ok=False, error=f"AI builder failed: {str(exc)[:300]}")

    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) if usage else 0
    out_tok = getattr(usage, "output_tokens", 0) if usage else 0

    tool_input: Optional[dict[str, Any]] = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "emit_strategy_graph":
            tool_input = block.input  # type: ignore[attr-defined]
            break

    if tool_input is None:
        return GraphPlan(
            ok=False,
            error="The AI did not return a structured graph. Try rephrasing.",
            input_tokens=in_tok,
            output_tokens=out_tok,
        )

    nodes, edges = _normalize_nodes_edges(
        tool_input.get("nodes") or [], tool_input.get("edges") or []
    )
    if not nodes:
        return GraphPlan(
            ok=False,
            error="The AI returned an empty graph. Try adding more detail.",
            input_tokens=in_tok,
            output_tokens=out_tok,
        )

    asset_class = tool_input.get("assetClass") or asset_class_hint or "crypto"
    return GraphPlan(
        ok=True,
        name=tool_input.get("name") or "Untitled Strategy",
        asset_class=asset_class,
        plan=[str(s) for s in (tool_input.get("plan") or [])],
        assumptions=[str(s) for s in (tool_input.get("assumptions") or [])],
        questions=[
            {"q": str(q.get("q", "")), "options": [str(o) for o in (q.get("options") or [])]}
            for q in (tool_input.get("questions") or [])
            if isinstance(q, dict) and q.get("q")
        ][:3],
        nodes=nodes,
        edges=edges,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def plan_graph_from_nl(
    nl_description: str,
    asset_class_hint: Optional[str] = None,
    context_graph: Optional[dict[str, Any]] = None,
) -> GraphPlan:
    """Turn an NL strategy description into a builder node graph (AI build chat)."""
    user_parts = [f"Strategy idea:\n{nl_description.strip()}"]
    if asset_class_hint:
        user_parts.append(f"\nPreferred asset class: {asset_class_hint}.")
    if context_graph and context_graph.get("nodes"):
        # Give the model the current canvas so a follow-up message refines
        # rather than rebuilds from scratch.
        user_parts.append(
            "\nThere is already a graph on the canvas. Revise it to honour the "
            "new instruction, keeping unrelated nodes intact:\n"
            + json.dumps(context_graph)[:8000]
        )
    return _run_emit(SYSTEM_PROMPT, "\n".join(user_parts), asset_class_hint)


def plan_graph_from_code(
    source_code: str,
    asset_class_hint: Optional[str] = None,
) -> GraphPlan:
    """Render the builder node graph that represents a strategy's PYTHON source.

    The reverse of graph->code translation. Best-effort VIEW: the Python source
    stays the source of truth, so a graph that can't capture every nuance is
    fine (the model notes gaps in `assumptions`).
    """
    code = (source_code or "").strip()
    if len(code) < 10:
        return GraphPlan(ok=False, error="No source code to render.")
    user_msg = (
        "Render the node graph that represents this strategy's Python source:\n\n"
        "```python\n" + code[:16000] + "\n```"
    )
    return _run_emit(CODE_SYSTEM_PROMPT, user_msg, asset_class_hint)
