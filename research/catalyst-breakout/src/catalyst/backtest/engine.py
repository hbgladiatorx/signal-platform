"""MODULE 6 -- backtest engine: sweep evaluate_signal across the historical panel.

For each (ticker, as_of) the engine:
  1. calls evaluate_signal with a panel bounded at as_of (PIT),
  2. if it fired, locates the T+1 OPEN as the entry (anti-bias rule #2),
  3. applies the do-not-chase rule at the T+1 open -- some signals get no fill,
  4. measures BOTH fixed-horizon return and rules-based realized P&L forward.

Survivorship: the ticker list is the as-of universe INCLUDING later-delisted
names (rule #3); delisted names simply run out of forward bars and exit at
'horizon_end' / last close.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any, Iterable

from ..store.db import Database
from ..store.panel import AsOfPanel
from .evaluate import evaluate_signal, SignalDecision
from .measure import fixed_horizon, rules_based, FixedHorizonResult, RulesResult
from config.defaults import Config, DEFAULTS


@dataclass
class Trade:
    ticker: str
    signal_date: str
    entry_date: str | None
    entry_price: float | None
    filled: bool
    no_fill_reason: str
    catalyst_type: str
    tier: str
    requires_review: bool
    fixed_horizon: dict[int, float | None] = field(default_factory=dict)
    rules_return: float | None = None
    rules_exit_reason: str | None = None
    holding_days: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _all_bars(db: Database, ticker: str) -> list[dict[str, Any]]:
    """Full price series (used for forward OUTCOME measurement only)."""
    return db.execute(
        "SELECT date, open, high, low, close, adj_close, volume FROM prices "
        "WHERE ticker = ? ORDER BY date ASC",
        (ticker,),
    )


def run_signal(
    db: Database,
    ticker: str,
    as_of: date | str,
    *,
    chain: list[dict[str, Any]] | None = None,
    chain_fetcher=None,
    cfg: Config = DEFAULTS,
) -> Trade | None:
    """Evaluate one (ticker, as_of), then fill at T+1 open and measure forward.

    chain_fetcher: optional fetch(ticker, as_of_date) -> normalized chain, used
    for the stage-two options overlay. Omit it to backtest the underlying signal
    edge first (Section 9 ordering).
    """
    as_of_str = as_of.isoformat() if isinstance(as_of, date) else as_of
    panel = AsOfPanel(db, as_of_str)
    if chain is None and chain_fetcher is not None:
        chain = chain_fetcher(ticker, date.fromisoformat(as_of_str))
    decision = evaluate_signal(ticker, as_of_str, panel, chain=chain, cfg=cfg)
    if decision is None or not decision.fired:
        return None

    bars = _all_bars(db, ticker)
    # Locate signal bar index, then entry is +entry_lag_bars (default T+1).
    sig_idx = next((i for i, b in enumerate(bars) if b["date"] == as_of_str), None)
    if sig_idx is None:
        return None
    entry_idx = sig_idx + cfg.backtest.entry_lag_bars
    if entry_idx >= len(bars):
        return _no_fill(decision, "no_next_bar")

    entry_bar = bars[entry_idx]
    entry_price = _num(entry_bar.get("open"))
    if entry_price is None:
        return _no_fill(decision, "no_open_price")

    # Do-not-chase applied at the T+1 OPEN (this is why some signals never fill).
    if decision.plan.do_not_chase_level is not None and entry_price > decision.plan.do_not_chase_level:
        return _no_fill(decision, "do_not_chase", entry_bar["date"])

    forward = bars[entry_idx + 1:]
    fh: FixedHorizonResult = fixed_horizon(entry_price, forward, cfg.backtest.forward_horizons_months)
    rb: RulesResult = rules_based(entry_price, forward, decision.plan)

    return Trade(
        ticker=ticker,
        signal_date=as_of_str,
        entry_date=entry_bar["date"],
        entry_price=entry_price,
        filled=True,
        no_fill_reason="",
        catalyst_type=decision.catalyst.catalyst_type,
        tier=decision.catalyst.tier,
        requires_review=decision.catalyst.requires_review,
        fixed_horizon=fh.returns,
        rules_return=rb.realized_return,
        rules_exit_reason=rb.exit_reason,
        holding_days=rb.holding_days,
    )


def _no_fill(decision: SignalDecision, reason: str, entry_date: str | None = None) -> Trade:
    return Trade(
        ticker=decision.ticker, signal_date=decision.as_of, entry_date=entry_date,
        entry_price=None, filled=False, no_fill_reason=reason,
        catalyst_type=decision.catalyst.catalyst_type, tier=decision.catalyst.tier,
        requires_review=decision.catalyst.requires_review,
    )


def sweep(
    db: Database,
    tickers: Iterable[str],
    dates: Iterable[date | str],
    *,
    chain_fetcher=None,
    cfg: Config = DEFAULTS,
) -> list[Trade]:
    """Full sweep across the historical panel. Returns every fired signal (incl.
    no-fills, so the report can measure the do-not-chase miss rate)."""
    trades: list[Trade] = []
    for ticker in tickers:
        for as_of in dates:
            t = run_signal(db, ticker, as_of, chain_fetcher=chain_fetcher, cfg=cfg)
            if t is not None:
                trades.append(t)
    return trades


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
