"""MODULE 6 (core) -- evaluate_signal: the point-in-time decision function.

    evaluate_signal(ticker, as_of) -> SignalDecision | None

Returns whether the FULL parameter stack (screen -> catalyst gate -> wrapper ->
entry/exit) fired using ONLY as-of-`as_of` data. It reads exclusively through
``get_pit_features`` / ``AsOfPanel``, so it is structurally incapable of lookahead.

CRITICAL: this function confirms on day T using T-close-knowable data. It does NOT
compute the fill. The do-not-chase rule is applied at T+1 OPEN by the engine
(``engine.py``), which is why some signals produce no fill. Entry is never on the
signal bar (anti-bias rule #2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..store.panel import AsOfPanel
from ..pit.features import get_pit_features, FeatureRow
from ..screen.distressed import passes_screen, ScreenResult
from ..catalysts.detectors import detect_from_panel
from ..catalysts.types import CatalystHit
from ..options.wrapper import select_wrapper, WrapperDecision
from ..signals.entryexit import build_plan, EntryExitPlan
from config.defaults import Config, DEFAULTS


@dataclass
class SignalDecision:
    ticker: str
    as_of: str
    fired: bool
    catalyst: CatalystHit | None = None
    screen: ScreenResult | None = None
    wrapper: WrapperDecision | None = None
    plan: EntryExitPlan | None = None
    features: FeatureRow | None = None
    reject_reason: str = ""

    @property
    def catalyst_type(self) -> str:
        return self.catalyst.catalyst_type if self.catalyst else "none"


def evaluate_signal(
    ticker: str,
    as_of: date | str,
    panel: AsOfPanel,
    *,
    chain: list[dict[str, Any]] | None = None,
    cfg: Config = DEFAULTS,
) -> SignalDecision | None:
    """Evaluate the full stack as of ``as_of``. Returns None if no as-of data."""
    row = get_pit_features(ticker, as_of, panel, cfg)
    if row is None:
        return None

    as_of_str = panel.as_of

    # Stage 1: distressed-and-viable screen.
    screen = passes_screen(row, cfg)
    if not screen.passed:
        return SignalDecision(ticker, as_of_str, fired=False, screen=screen,
                              features=row, reject_reason="failed_screen")

    # Stage 2: catalyst gate. Only a FRESH catalyst (knowable within window) fires.
    fresh = _fresh_catalysts(row, as_of_str, cfg)
    if not fresh:
        return SignalDecision(ticker, as_of_str, fired=False, screen=screen,
                              features=row, reject_reason="no_fresh_catalyst")
    # Highest-priority catalyst: validator tier first, then most recent.
    catalyst = sorted(fresh, key=lambda c: (c.tier == "validator", c.knowable_at), reverse=True)[0]

    # Stage 3: options wrapper.
    wrapper = select_wrapper(
        chain=chain or [],
        spot=row.price or 0.0,
        iv_rank=row.iv_rank,
        iv_rank_reliable=row.iv_rank_reliable,
        catalyst_resolution=None,
        as_of=date.fromisoformat(as_of_str),
        target_price=None,
        slow_grind=False,
        market_cap=row.market_cap,
        cfg=cfg,
    )

    # Stage 4: entry/exit plan (do-not-chase level computed from T data; the
    # T+1-open check happens in the engine, not here).
    plan = build_plan(
        row,
        catalyst_trigger_price=row.price or 0.0,
        eval_price=None,
        cfg=cfg,
    )

    return SignalDecision(
        ticker, as_of_str, fired=True, catalyst=catalyst, screen=screen,
        wrapper=wrapper, plan=plan, features=row,
    )


def _fresh_catalysts(row: FeatureRow, as_of: str, cfg: Config) -> list[CatalystHit]:
    """Catalysts that became knowable recently (within the relevant window)."""
    from datetime import timedelta

    hits = detect_from_panel(row, cfg)
    cutoff = (date.fromisoformat(as_of) - timedelta(
        days=max(cfg.catalyst.analyst_revision_window_days, cfg.catalyst.insider_window_days, 5)
    )).isoformat()
    return [h for h in hits if h.knowable_at[:10] >= cutoff]
