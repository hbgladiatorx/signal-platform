"""Backtest analysis — turn the structured attribution + ML edge + metrics of a
backtest into concrete, human-readable findings ("what worked, what to tweak,
why, what to fix").

The deterministic engine (`analyze_backtest`) needs no external services and is
the source of truth. An optional LLM narrative layer (`narrate.py`) writes prose
on top when an Anthropic key with credit is available; it degrades gracefully to
the deterministic findings when it is not.
"""
from packages.analysis.backtest_analysis import analyze_backtest  # noqa: F401
from packages.analysis.narrate import generate_narrative  # noqa: F401
from packages.analysis.tweak_advisor import suggest_param_tweaks  # noqa: F401
from packages.analysis.walkforward_analysis import analyze_walkforward  # noqa: F401
