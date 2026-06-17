"""Optional LLM narrative layer over the deterministic backtest analysis.

The deterministic engine (`backtest_analysis.analyze_backtest`) already produces
the findings; this turns them into a short, plain-English narrative a trader can
read top-to-bottom. It is BEST-EFFORT: if the `anthropic` package is missing,
no API key is set, or the key is out of credit, it returns a structured failure
instead of raising, and the caller falls back to the deterministic findings.

Kept out of the backtest worker's hot path on purpose — generating prose for
every run would be slow and burn tokens. The API exposes it on-demand.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)

# claude-sonnet-4-6 is the current Sonnet; claude-sonnet-4-20250514 was retired
# and now 404s. Override via env if needed.
NARRATE_MODEL = os.environ.get("NARRATE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """\
You are a senior quantitative trading analyst reviewing a single backtest for \
the strategy's author. You are given a STRUCTURED, already-computed analysis \
(verdict, metrics, and a ranked list of findings derived arithmetically from \
the backtest's attribution and an ML signal-edge model). Every number is \
authoritative — do NOT invent or recompute metrics, and do NOT contradict the \
findings.

Write a concise, direct narrative (180-260 words) with three clearly labelled \
parts:
  1. **What worked** — the genuine strengths, grounded in the findings.
  2. **Why it works / why it doesn't** — the mechanism: tie win rate, payoff, \
     and the per-signal / per-symbol edge together into a causal story.
  3. **What to fix** — the 2-4 highest-leverage, concrete changes, ordered by \
     impact. Reference specific signals/symbols by name.

Be honest about weak or low-sample results; never oversell. No preamble, no \
restating the question. Use plain language a competent trader understands. \
Markdown bold for the three part labels only."""


@dataclass
class NarrativeResult:
    ok: bool
    narrative: Optional[str] = None
    error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0


def _user_message(analysis: dict[str, Any], strategy_name: str | None) -> str:
    """Compact, LLM-friendly rendering of the deterministic analysis."""
    payload = {
        "strategy": strategy_name,
        "verdict": analysis.get("verdict"),
        "score_0_100": analysis.get("score"),
        "headline": analysis.get("headline"),
        "metrics": analysis.get("metrics"),
        "findings": [
            {
                "severity": f.get("severity"),
                "kind": f.get("kind"),
                "title": f.get("title"),
                "detail": f.get("detail"),
                "suggestion": f.get("suggestion"),
            }
            for f in analysis.get("findings", [])
        ],
    }
    return (
        "Here is the structured analysis of the backtest. Write the narrative "
        "as instructed.\n\n```json\n"
        + json.dumps(payload, indent=2, default=str)
        + "\n```"
    )


def generate_narrative(
    analysis: dict[str, Any],
    strategy_name: str | None = None,
) -> NarrativeResult:
    """Best-effort LLM narrative. Never raises; returns ok=False on any issue."""
    try:
        from anthropic import Anthropic, APIError, APITimeoutError
    except ImportError:
        return NarrativeResult(
            ok=False,
            error="The 'anthropic' package is not installed in this container.",
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return NarrativeResult(
            ok=False, error="ANTHROPIC_API_KEY is not set in this environment."
        )

    client = Anthropic(api_key=api_key, timeout=60.0)
    try:
        resp = client.messages.create(
            model=NARRATE_MODEL,
            max_tokens=900,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_message(analysis, strategy_name)}],
        )
    except APITimeoutError:
        return NarrativeResult(ok=False, error="LLM request timed out after 60s.")
    except APIError as e:
        # Out-of-credit, rate-limit, auth, etc. all land here — surface a clean,
        # user-readable reason rather than a stack trace.
        msg = str(e)
        if "credit" in msg.lower() or "balance" in msg.lower():
            msg = "Anthropic credit balance is too low — top up to enable AI narratives."
        log.warning("narrate.api_error err=%s", e)
        return NarrativeResult(ok=False, error=f"{msg}")
    except Exception as e:  # noqa: BLE001
        log.exception("narrate.unexpected_error")
        return NarrativeResult(ok=False, error=f"Unexpected LLM error: {type(e).__name__}")

    text = "".join(
        getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()
    if not text:
        return NarrativeResult(ok=False, error="LLM returned no text.")
    usage = getattr(resp, "usage", None)
    return NarrativeResult(
        ok=True,
        narrative=text,
        input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
    )
