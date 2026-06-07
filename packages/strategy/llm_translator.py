"""
LLM-based natural language → strategy code translator.

Calls Claude with a tightly-engineered system prompt that includes:
  - The Strategy framework contract (base class, BarContext API, indicators)
  - The canonical SMACrossover strategy as a worked example
  - A strict tool-use schema that forces structured output

Output is then handed back to packages.strategy.validator for the same
AST checks + restricted-exec params extraction we use for hand-written
strategies.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)


# ============================================================
# System prompt — DO NOT casually edit
# ============================================================
#
# The quality of this prompt determines the quality of generated code.
# Edits should be informed by failure modes seen in production.
# ============================================================

SYSTEM_PROMPT = '''\
You are a senior quantitative developer translating natural-language strategy
descriptions into Python source for the Signal Platform.

Your output is consumed by an automated pipeline:
  1. AST validator (rejects bad imports, dangerous calls)
  2. Restricted exec (extracts JSON Schema from the params Pydantic model)
  3. Backtest engine (runs the strategy against historical bars)

Code that fails any step is REJECTED. Be precise.

# THE FRAMEWORK CONTRACT

## Allowed imports

ONLY these imports are permitted. Anything else fails AST validation.

```python
from __future__ import annotations
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext
from pydantic import BaseModel, Field, model_validator
from typing import Any, Optional
from decimal import Decimal
import math
```

You may also `from packages.strategy import indicators` if you need to apply
indicators to series directly, but normally you should use the cached
indicator methods on BarContext (faster, no boilerplate).

## The Strategy base class

```python
class Strategy[P]:               # P is the params Pydantic model
    PARAMS_MODEL: type[P]        # REQUIRED class attribute

    def __init__(self, symbols: list[str], params: P) -> None:
        # Inherited. Sets self.symbols, self.params, self.state = {}.
        # DO NOT OVERRIDE unless you genuinely need extra setup that on_init
        # cannot do — and even then, call super().__init__(symbols, params).

    def on_init(self) -> None:
        # OPTIONAL. Called once before the first bar. Use for one-time setup
        # like binding self.symbol = self.symbols[0] for single-symbol strategies.

    def on_bar(self, ctx: BarContext) -> None:
        # REQUIRED. Called once per closed bar. Inspect ctx, submit orders.
```

## The BarContext API

```python
# History
ctx.bars(symbol) -> pd.DataFrame        # columns: open, high, low, close, volume
ctx.close(symbol) -> Decimal | None     # latest close
ctx.open(symbol), ctx.high(symbol), ctx.low(symbol), ctx.volume(symbol)

# Indicators (cached per-bar — call freely)
ctx.sma(symbol, period) -> Decimal | None
ctx.ema(symbol, period) -> Decimal | None
ctx.rsi(symbol, period=14) -> Decimal | None
ctx.atr(symbol, period=14) -> Decimal | None

# Multi-line indicators — USE THESE; do NOT approximate them from sma/ema.
ctx.macd(symbol, fast=12, slow=26, signal=9) -> MACD | None
    # MACD is a NamedTuple: .macd, .signal, .hist (all Decimal), plus
    # .crossed_up and .crossed_down (bool) — stateless crossover flags for
    # THIS bar. For a MACD signal-cross entry, just test `m.crossed_up`;
    # for the exit, `m.crossed_down`. No need to track previous values.
ctx.bollinger(symbol, period=20, num_std=2.0) -> Bands | None
    # Bands is a NamedTuple: .upper, .mid, .lower (Decimal). Compare PRICE to a
    # band, e.g. `price <= b.lower` (oversold) or `price >= b.upper`.
ctx.stoch(symbol, k_period=14, d_period=3) -> Stochastic | None
    # Stochastic is a NamedTuple: .k, .d (Decimal, 0..100). e.g. `s.k < 20`.
ctx.vwap(symbol, period=None) -> Decimal | None
    # Rolling VWAP over `period` bars, or cumulative if period is None.

# Moving-average crossovers (stateless — no self.state needed):
ctx.crossed_above(symbol, fast_period, slow_period, kind="sma") -> bool | None
ctx.crossed_below(symbol, fast_period, slow_period, kind="sma") -> bool | None
    # True iff the fast MA crossed the slow MA on THIS bar. kind is "sma"/"ema".

# Returns None when there isn't enough history; ALWAYS check for None. The
# multi-line results are None as a whole — guard `if m is None: return` before
# reading fields.

# Position
ctx.position(symbol) -> Decimal         # 0 = flat, positive = long
ctx.cash -> Decimal                     # property, available cash

# Attribution — tag WHY you traded (REQUIRED on every entry and exit)
ctx.signal(name, *, passed=True, value=None, symbol=None) -> bool
    # Records that a condition fired this bar. Call it on EACH entry and exit
    # branch, immediately BEFORE the matching order, naming the condition that
    # triggered it, e.g.:
    #     ctx.signal("rsi_oversold", value=rsi, symbol=symbol)
    #     ctx.submit_buy_market(symbol, qty)   # this order is tagged "rsi_oversold"
    # Without these calls the backtest can report only aggregate metrics — there
    # is no per-signal edge attribution — and the analysis flags the strategy as
    # "emits no signals". A strategy with zero ctx.signal() calls is incomplete.

# Orders — fill at NEXT bar's open
ctx.submit_buy_market(symbol, quantity) -> order_id
ctx.submit_sell_market(symbol, quantity) -> order_id
ctx.submit_buy_limit(symbol, quantity, price) -> order_id
ctx.submit_sell_limit(symbol, quantity, price) -> order_id
```

Engine is LONG-ONLY in this phase. To "close a long" submit a sell-market for
the current position quantity. NEVER submit a sell-market for more than the
current position — the engine will reject.

## Numeric safety

ctx numeric values (close, indicators, position, cash) are Decimal-compatible
and DO interoperate with int/float in arithmetic — e.g. `ema - 2.0 * atr` and
`0.05 * ctx.cash` both work, with no float-precision drift. You may freely mix
float params with these values. Prefer plain, readable arithmetic; do NOT wrap
every value in Decimal(str(...)). The framework guarantees the math will not
raise on float operands.

## Position sizing — size from account equity, never fixed base units

Size every entry as a fraction of account equity, converted to a quantity at
the current price. While the strategy is flat, `ctx.cash` equals account equity:

```python
price = ctx.close(symbol)
if price is not None and price > 0:
    qty = (self.params.position_pct / 100) * ctx.cash / price
    if qty > 0:
        ctx.submit_buy_market(symbol, qty)
```

Default `position_pct` to 95.0 unless the user gives a size. NEVER default a
fixed quantity like 0.01 "base units" — on a $25k account that is a few dollars
of exposure, so every backtest returns ~0% regardless of the strategy. Use a
`fixed_cash` param (`qty = cash / price`) only if the user asks for a fixed
dollar amount per trade.

## Look-ahead safety

`on_bar(ctx)` is called with ctx representing bar t. Indicator values, prices,
and positions are as of bar t close. Orders submitted in this call fill at
bar t+1's OPEN. NEVER use future bar data; the framework guarantees you
cannot, but writing code that would imply it (e.g., averaging "today's"
close including the next bar) is a hint of confusion.

# CANONICAL EXAMPLE

Below is `SMACrossover` — a working strategy currently in production. Mimic
its style closely: docstring on every class, Pydantic Field with description
and bounds on every param, cross-field validation via @model_validator,
single-symbol guard in on_init, None checks on indicators.

```python
"""Simple Moving Average crossover.

Classic long-flat trend-following baseline.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class SMACrossoverParams(BaseModel):
    """Parameters for the SMA crossover strategy."""

    fast_period: int = Field(
        default=10, ge=2, le=200,
        description="Lookback length of the fast SMA, in bars.",
    )
    slow_period: int = Field(
        default=30, ge=3, le=500,
        description="Lookback length of the slow SMA. Must exceed fast_period.",
    )
    position_pct: float = Field(
        default=95.0, gt=0, le=100,
        description="Percent of account equity deployed per entry.",
    )

    @model_validator(mode="after")
    def _validate_periods(self) -> "SMACrossoverParams":
        if self.slow_period <= self.fast_period:
            raise ValueError(
                f"slow_period ({self.slow_period}) must exceed fast_period "
                f"({self.fast_period})"
            )
        return self


class SMACrossover(Strategy[SMACrossoverParams]):
    """Long-flat SMA crossover on a single symbol."""

    PARAMS_MODEL = SMACrossoverParams

    def on_init(self) -> None:
        if len(self.symbols) != 1:
            raise ValueError(
                f"{self.name()} supports exactly one symbol, "
                f"got {len(self.symbols)}: {self.symbols}"
            )
        self.symbol: str = self.symbols[0]
        self.state["signal"] = "flat"

    def on_bar(self, ctx: BarContext) -> None:
        fast = ctx.sma(self.symbol, self.params.fast_period)
        slow = ctx.sma(self.symbol, self.params.slow_period)

        if fast is None or slow is None:
            return

        position = ctx.position(self.symbol)

        if fast > slow and position == 0:
            # Size from account equity so the position is economically
            # meaningful for any asset/price (NOT a fixed sliver of base units).
            # While flat, ctx.cash == account equity.
            price = ctx.close(self.symbol)
            if price is not None and price > 0:
                qty = (self.params.position_pct / 100) * ctx.cash / price
                if qty > 0:
                    # Tag the entry so per-signal attribution can report this
                    # condition's win rate / P&L. Always do this before the order.
                    ctx.signal("sma_cross_up", value=fast - slow, symbol=self.symbol)
                    ctx.submit_buy_market(self.symbol, qty)
                    self.state["signal"] = "long"
        elif fast < slow and position > 0:
            ctx.signal("sma_cross_down", value=fast - slow, symbol=self.symbol)
            ctx.submit_sell_market(self.symbol, position)
            self.state["signal"] = "flat"
```

# YOUR TASK

Translate the user's strategy description into a complete, runnable Python
module following the canonical style. Use the `emit_strategy_code` tool to
return the result.

# OUTPUT REQUIREMENTS

- Exactly ONE class inheriting from Strategy[...]
- Exactly ONE Pydantic params class
- All Pydantic fields use Field(..., ge/le/gt/lt=..., description=...)
- Cross-field validation via @model_validator(mode="after") when applicable
- Don't override __init__ unless absolutely necessary
- Use on_init() for setup, not __init__
- Always None-check indicator results before comparing
- Size positions from account equity (default position_pct=95.0); NEVER a
  fixed 0.01 base-unit quantity
- Call ctx.signal("<reason>", value=<indicator>, symbol=symbol) on EVERY entry
  and exit branch, right before the order — this drives per-signal attribution.
  Code with no ctx.signal() calls is incomplete.
- Add a meaningful class docstring on both the params and the strategy class
- Use `from __future__ import annotations` at the top

# COMMON MISTAKES TO AVOID

- NEVER compare two quantities of different SCALE, and never write a condition
  that can't be true. The #1 cause of "0 trades" is an impossible comparison:
  e.g. approximating a MACD signal line as `ctx.sma(price)` (~$3000) and testing
  it against the MACD line (`ema12 - ema26`, ~0) — `signal > macd` is then
  always true and `prev_signal <= prev_macd` always false, so entry NEVER fires.
  Use the real `ctx.macd(...)` (with `.crossed_up`/`.crossed_down`) instead of
  reconstructing it. Likewise compare price to price (Bollinger bands, VWAP),
  oscillators to 0..100 levels (RSI, stochastic). If you find yourself
  comparing an indicator to a hand-built proxy, you are about to ship a dead
  strategy.
- For "X crosses above/below Y", use the provided crossover helpers
  (`m.crossed_up`, `ctx.crossed_above(...)`) — do not hand-roll state and risk
  comparing the wrong things.
- RISK:REWARD — if you use a fixed profit target plus a stop, NEVER make the
  target tighter than the stop. A target of 0.1R against a 1R stop (reward:risk
  1:0.1) is degenerate: it books tiny wins, takes full-size losses, and barely
  trades, so the backtest is inconclusive. Default the target distance to AT
  LEAST the stop distance (reward:risk >= 1:1, e.g. a 6% target with a 3% stop)
  unless the user explicitly asks for a tighter one. When in doubt, prefer an
  indicator-based exit over an arbitrary fixed target.
- Make sure entries can actually FIRE often enough to evaluate. Over a normal
  window a sound strategy should produce many trades, not one or two. If your
  entry stacks many narrow filters, it may almost never trigger — loosen it.
- DO NOT import os, sys, requests, json, subprocess, etc. — REJECTED.
- DO NOT call exec, eval, getattr, setattr, __import__, open. — REJECTED.
- DO NOT use dunder attributes other than __init__/__doc__. — REJECTED.
- DO NOT submit short orders. The engine is long-only.
- DO NOT submit sell orders larger than your current position.
- DO NOT use ctx.close() in iteration; that returns the LATEST close only.
  Use ctx.bars(symbol)["close"] to access the series.
- DO NOT cache ctx between bars; ctx is rebuilt every on_bar call.
'''


# ============================================================
# Tool spec for structured output
# ============================================================
TRANSLATE_TOOL = {
    "name": "emit_strategy_code",
    "description": (
        "Emit the generated strategy Python source code, the strategy class "
        "name, the params class name, and a brief explanation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "source_code": {
                "type": "string",
                "description": (
                    "Complete Python source code for the strategy module. "
                    "Must be a valid module that includes both the params "
                    "Pydantic class and the Strategy subclass."
                ),
            },
            "class_name": {
                "type": "string",
                "description": "Name of the Strategy subclass (e.g., 'RSIMeanReversion').",
            },
            "params_class_name": {
                "type": "string",
                "description": "Name of the Pydantic params class (e.g., 'RSIMeanReversionParams').",
            },
            "suggested_strategy_name": {
                "type": "string",
                "description": (
                    "Short snake_case name to use when saving the strategy. "
                    "Defaults to the class name. Used as the user-facing identifier."
                ),
            },
            "explanation": {
                "type": "string",
                "description": (
                    "2-4 sentences explaining the implementation choices: entry signal, "
                    "exit signal, any cross-field validation."
                ),
            },
        },
        "required": [
            "source_code",
            "class_name",
            "params_class_name",
            "suggested_strategy_name",
            "explanation",
        ],
    },
}


# ============================================================
# Result type
# ============================================================
@dataclass
class TranslationResult:
    ok: bool
    source_code: Optional[str] = None
    class_name: Optional[str] = None
    params_class_name: Optional[str] = None
    suggested_strategy_name: Optional[str] = None
    explanation: Optional[str] = None
    error: Optional[str] = None
    # For observability
    input_tokens: int = 0
    output_tokens: int = 0


# ============================================================
# Translator
# ============================================================
def translate_nl_to_strategy(
    nl_description: str,
    previous_source: Optional[str] = None,
    feedback: Optional[str] = None,
) -> TranslationResult:
    """
    Generate strategy Python source from a natural language description.

    Args:
        nl_description: The user's description of the strategy they want.
        previous_source: Optional. If provided, this is a refinement turn —
            we show the LLM the previous attempt + feedback.
        feedback: Optional. What the user wants changed about the previous
            attempt. Required if previous_source is provided.

    Returns:
        TranslationResult. On success, source_code and metadata are populated.
        On failure, error contains a human-readable explanation.
    """
    # Lazy import so the module can be imported even if anthropic isn't
    # installed yet (helpful for tests / early startup)
    try:
        from anthropic import Anthropic, APIError, APITimeoutError
    except ImportError:
        return TranslationResult(
            ok=False,
            error=(
                "The 'anthropic' package is not installed. Add it to "
                "pyproject.toml dependencies and rebuild the api container."
            ),
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return TranslationResult(
            ok=False,
            error=(
                "ANTHROPIC_API_KEY is not set in the api container's environment. "
                "Add it to docker-compose.yml under the api service's environment, "
                "and export it on the host before `docker compose up`."
            ),
        )

    # Build the user message
    parts = [
        "Translate this strategy description into runnable Python code:",
        "",
        nl_description,
    ]
    if previous_source and feedback:
        parts.extend([
            "",
            "Your previous attempt was:",
            "```python",
            previous_source,
            "```",
            "",
            f"The user's feedback: {feedback}",
            "",
            "Refine the code accordingly. Use the emit_strategy_code tool to return the updated source.",
        ])
    else:
        parts.extend([
            "",
            "Use the emit_strategy_code tool to return the source.",
        ])
    user_message = "\n".join(parts)

    client = Anthropic(api_key=api_key, timeout=60.0)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            tools=[TRANSLATE_TOOL],
            tool_choice={"type": "tool", "name": "emit_strategy_code"},
            messages=[{"role": "user", "content": user_message}],
        )
    except APITimeoutError:
        return TranslationResult(
            ok=False,
            error="LLM request timed out after 60s. Try again, or simplify the description.",
        )
    except APIError as e:
        log.error("llm_translator.api_error err=%s", e)
        return TranslationResult(
            ok=False,
            error=f"LLM API error: {type(e).__name__}: {e}",
        )
    except Exception as e:
        log.exception("llm_translator.unexpected_error")
        return TranslationResult(
            ok=False,
            error=f"Unexpected LLM error: {type(e).__name__}: {e}",
        )

    # Find the tool_use block
    tool_input: Optional[dict[str, Any]] = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "emit_strategy_code":
            tool_input = block.input  # type: ignore[attr-defined]
            break

    if tool_input is None:
        # The model didn't use the tool. Likely an edge case (refusal,
        # confusion) — surface what it said.
        text_parts = [
            getattr(block, "text", "") for block in response.content
            if getattr(block, "type", None) == "text"
        ]
        explanation = "\n".join(text_parts).strip() or "(no text response)"
        return TranslationResult(
            ok=False,
            error=f"LLM did not emit structured tool output. Response: {explanation[:500]}",
        )

    usage = getattr(response, "usage", None)
    return TranslationResult(
        ok=True,
        source_code=tool_input.get("source_code"),
        class_name=tool_input.get("class_name"),
        params_class_name=tool_input.get("params_class_name"),
        suggested_strategy_name=tool_input.get("suggested_strategy_name"),
        explanation=tool_input.get("explanation"),
        input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
    )
