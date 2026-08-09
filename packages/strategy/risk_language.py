"""
Deterministic risk-language disambiguation.

A phrase like "risk 2% per trade" is economically ambiguous: it can mean either
a 2% POSITION SIZE (deploy 2% of equity) or a 2% STOP-LOSS (exit when the trade
is down 2%). Those are opposite economics — one caps exposure, the other caps
loss per trade — and they produce materially different strategies. Until now both
build paths (the deterministic graph compiler and the LLM translator) resolved
the phrase silently, so a user could type one thing and get a strategy that does
something else and never know.

This module is the single source of truth that BOTH paths consult, so they can't
disagree. It does ONE thing: scan a free-text description for risk language and,
when a phrase is ambiguous between position-size and stop-loss, return a
machine-readable flag recording (a) that it was ambiguous, (b) which
interpretation was applied as the documented default, and (c) that the user
should confirm or correct it. Unambiguous phrases ("2% stop", "position size
2%") return no flag — they compile exactly as before.

THE DOCUMENTED DEFAULT — when a bare "risk N%" is left unclarified, we apply a
STOP-LOSS of N%. Rationale: "risk per trade" conventionally denotes the loss a
trader is willing to take on a trade, and a stop-loss is the mechanism that
literally bounds that loss. Interpreting it as position size instead would
deploy only N% of equity (≈2% exposure for "risk 2%"), which makes the P&L
nearly flat and is almost never what the user meant. The default is recorded
explicitly in the flag so it is never hidden.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# The documented default interpretation for an unclarified ambiguous "risk N%".
DEFAULT_INTERPRETATION = "stop_loss"
ALTERNATIVE_INTERPRETATION = "position_size"
DEFAULT_RATIONALE = (
    '"Risk N% per trade" conventionally means the loss you are willing to take '
    "on the trade, so the default applies it as an N% stop-loss (cap loss per "
    "trade) rather than an N% position size (deploy N% of equity)."
)

# A percent magnitude: "2%", "2 %", "2 percent", "2.5pct".
_PCT = r"(\d+(?:\.\d+)?)\s*(?:%|percent|pct)"

# Keywords that, when bound to a percent, make it UNAMBIGUOUSLY a stop-loss.
_STOP_KW = re.compile(r"\bstop(?:[-\s]?loss)?\b|\bsl\b|\btrailing\b", re.I)
# Keywords that, when bound to a percent, make it UNAMBIGUOUSLY a position size.
_SIZE_KW = re.compile(
    r"\bposition\s*size\b|\bsize\b|\ballocat\w*\b|\bdeploy\w*\b|\binvest\w*\b"
    r"|\bof\s+(?:account|equity|capital|portfolio|balance|nav)\b"
    r"|\bbet\s*size\b|\bexposure\b",
    re.I,
)
# The ambiguity trigger: the word "risk"/"risking" bound to a percent.
_RISK_KW = re.compile(r"\brisk\w*\b", re.I)

# How far on either side of the percent we look for a disambiguating keyword.
_WINDOW = 28


@dataclass
class RiskFlag:
    """A machine-readable clarification flag for an ambiguous risk phrase."""

    ambiguous: bool
    phrase: str  # the matched snippet, e.g. "risk 2% per trade"
    value: float  # the percent magnitude, e.g. 2.0
    applied_interpretation: str  # the default that was applied, e.g. "stop_loss"
    alternative_interpretation: str  # the meaning NOT applied
    default_rationale: str
    needs_confirmation: bool
    message: str  # human-readable, safe to show in the UI

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "risk_ambiguity",
            "ambiguous": self.ambiguous,
            "phrase": self.phrase,
            "value": self.value,
            "applied_interpretation": self.applied_interpretation,
            "alternative_interpretation": self.alternative_interpretation,
            "default_rationale": self.default_rationale,
            "needs_confirmation": self.needs_confirmation,
            "message": self.message,
        }


def _snippet(text: str, start: int, end: int) -> str:
    lo = max(0, start - _WINDOW)
    hi = min(len(text), end + _WINDOW)
    return text[lo:hi].strip()


def has_unambiguous_size_language(text: str | None) -> bool:
    """True iff `text` binds a percent to an explicit position-size keyword
    (e.g. "size 2% of account", "position size 5%"). Used by the compiler to
    tell a genuine sizing instruction from a positionSize node the planner
    produced by silently misreading an ambiguous "risk N%"."""
    if not text:
        return False
    for m in re.finditer(_PCT, text, re.I):
        window = _snippet(text, m.start(), m.end())
        if _SIZE_KW.search(window) and not _STOP_KW.search(window):
            return True
    return False


def detect_risk_ambiguity(text: str | None) -> RiskFlag | None:
    """Return a RiskFlag iff `text` contains a risk phrase that is ambiguous
    between position-size and stop-loss. Returns None when there is no risk
    language, or when every risk percent is unambiguously a stop or a size.

    This is pure and deterministic — the same text always yields the same flag —
    so both compile paths produce identical results.
    """
    if not text:
        return None

    for m in re.finditer(_PCT, text, re.I):
        window = _snippet(text, m.start(), m.end())
        has_stop = bool(_STOP_KW.search(window))
        has_size = bool(_SIZE_KW.search(window))
        has_risk = bool(_RISK_KW.search(window))

        # Unambiguous: a stop OR a size keyword is bound to this percent (and not
        # both). Compile it directly, no flag.
        if has_stop != has_size and (has_stop or has_size):
            continue

        # Ambiguous: a "risk N%" with no disambiguating keyword (or with BOTH a
        # stop and size keyword nearby, which is genuinely contradictory). This
        # is the economics-flipping case we refuse to resolve silently.
        if has_risk:
            value = float(m.group(1))
            return RiskFlag(
                ambiguous=True,
                phrase=_snippet(text, m.start(), m.end()),
                value=value,
                applied_interpretation=DEFAULT_INTERPRETATION,
                alternative_interpretation=ALTERNATIVE_INTERPRETATION,
                default_rationale=DEFAULT_RATIONALE,
                needs_confirmation=True,
                message=(
                    f'"{_snippet(text, m.start(), m.end())}" is ambiguous: it '
                    f"could mean a {value:g}% stop-loss (cap loss per trade) or a "
                    f"{value:g}% position size (deploy {value:g}% of equity). These "
                    f"are opposite economics. Applied the default — a {value:g}% "
                    f"stop-loss. Confirm this is what you meant, or say "
                    f'"size {value:g}% of account" / "{value:g}% stop" to be explicit.'
                ),
            )

    return None
