"""Performance analytics for a BacktestResult.

Takes a `BacktestResult` produced by `run_backtest()` and computes the
metrics a quant uses to evaluate strategy performance:

  Return metrics:
    total_return_pct        — simple final/initial - 1
    annualized_return_pct   — total_return projected to a 365.25-day year

  Risk metrics:
    sharpe_ratio            — annualized excess-return / volatility
    sortino_ratio           — Sharpe but only downside volatility
    max_drawdown_pct        — largest peak-to-trough equity decline
    calmar_ratio            — annualized_return / |max_drawdown|

  Trade metrics:
    num_closed_trades       — completed round trips
    num_open_trades         — positions still open at end of backtest
    win_rate_pct            — % of closed round trips with net_pnl > 0
    profit_factor           — gross_wins / gross_losses (None if no losses)
    avg_winner_pct          — mean return % over winning round trips
    avg_loser_pct           — mean return % over losing round trips
    avg_trade_duration_s    — mean entry→exit time in seconds

Round-trip pairing uses position-zero segmentation: a round trip is the
sequence of fills that takes a symbol's position from 0 to nonzero and
back to 0. Open positions (no closing fill yet) are tracked separately
and excluded from win-rate / profit-factor calculations to avoid
contaminating those metrics with hypothetical mark-to-market values.

Sharpe annualization uses periods_per_year inferred from the median
time-delta between equity-curve points. For 1h crypto bars this is
24 * 365 = 8,760. Caveat: high-frequency Sharpes can look inflated; the
ratio is most reliable on daily-or-coarser bars with hundreds of samples.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

import pandas as pd

from packages.backtest.types import BacktestResult, EquityPoint, Fill
from packages.strategy.base import OrderSide


SECONDS_PER_YEAR = 365.25 * 86_400  # 31,557,600


# ============================================================
# Data classes
# ============================================================
@dataclass(frozen=True)
class RoundTrip:
    """A completed entry-exit cycle on a single symbol.

    Phase 2 is long-only, so `side` is always 'long'. The cycle starts when
    a buy takes the position from 0 to positive and ends when one or more
    sells bring it back to 0. Aggregates over multiple entry / exit fills
    within the cycle.
    """

    symbol: str
    side: str  # 'long' (Phase 2 longs only)
    entry_ts: datetime
    exit_ts: datetime
    entry_avg_price: Decimal
    exit_avg_price: Decimal
    quantity: Decimal
    gross_pnl: Decimal  # (exit_avg - entry_avg) * quantity, ignoring fees
    fees: Decimal       # sum of fees across all fills in this trip
    net_pnl: Decimal    # gross_pnl - fees
    duration_seconds: float
    num_fills: int
    # Attribution: the signal/filter names that were active on the entry
    # (buy) fills of this trip. Drives per-signal P&L breakdown. Empty when
    # the strategy emitted no signals. Ordered, de-duplicated.
    entry_tags: tuple[str, ...] = ()


@dataclass
class BacktestAnalytics:
    """Computed metrics over a BacktestResult."""

    # ----- Return metrics -----
    total_return_pct: float
    annualized_return_pct: float | None

    # ----- Risk metrics -----
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown_pct: float  # always <= 0
    max_drawdown_peak_ts: datetime | None
    max_drawdown_trough_ts: datetime | None
    calmar_ratio: float | None

    # ----- Trade metrics -----
    num_closed_trades: int
    num_open_trades: int
    win_rate_pct: float | None
    avg_winner_pct: float | None
    avg_loser_pct: float | None
    profit_factor: float | None
    avg_trade_duration_seconds: float | None

    # ----- Reference data -----
    closed_round_trips: list[RoundTrip] = field(default_factory=list)
    periods_per_year: float = 0.0  # inferred from equity curve cadence


# ============================================================
# Round-trip extraction
# ============================================================
def _extract_round_trips(
    fills: list[Fill],
) -> tuple[list[RoundTrip], list[Fill]]:
    """Walk fills per-symbol, segmenting into closed round trips.

    Returns (closed_trips, open_position_fills). Open fills are those
    whose symbol's running position never returned to zero by the end.
    """
    closed: list[RoundTrip] = []
    open_fills: list[Fill] = []

    by_symbol: dict[str, list[Fill]] = {}
    for fill in fills:
        by_symbol.setdefault(fill.symbol, []).append(fill)

    for symbol, sym_fills in by_symbol.items():
        sym_fills.sort(key=lambda f: f.filled_ts)
        current: list[Fill] = []
        position: Decimal = Decimal(0)

        for fill in sym_fills:
            current.append(fill)
            if fill.side == OrderSide.BUY:
                position += fill.quantity
            else:
                position -= fill.quantity

            if position == 0 and current:
                closed.append(_round_trip_from_fills(current))
                current = []

        # Anything leftover represents an open round trip
        open_fills.extend(current)

    return closed, open_fills


def _round_trip_from_fills(fills: list[Fill]) -> RoundTrip:
    """Aggregate a closed sequence of fills into a single RoundTrip."""
    symbol = fills[0].symbol
    buys = [f for f in fills if f.side == OrderSide.BUY]
    sells = [f for f in fills if f.side == OrderSide.SELL]

    buy_qty = sum((f.quantity for f in buys), Decimal(0))
    sell_qty = sum((f.quantity for f in sells), Decimal(0))

    buy_value = sum((f.price * f.quantity for f in buys), Decimal(0))
    sell_value = sum((f.price * f.quantity for f in sells), Decimal(0))
    fees = sum((f.fee for f in fills), Decimal(0))

    buy_avg = (buy_value / buy_qty) if buy_qty > 0 else Decimal(0)
    sell_avg = (sell_value / sell_qty) if sell_qty > 0 else Decimal(0)

    # Direction is set by the FIRST fill: buy-first = long, sell-first = short.
    # P&L is sells − buys either way (it nets correctly for both directions);
    # only the entry/exit labelling and tag source depend on direction.
    is_short = fills[0].side == OrderSide.SELL
    if is_short:
        side = "short"
        entry_avg, exit_avg = sell_avg, buy_avg
        quantity = sell_qty
        entry_side_fills = sells
    else:
        side = "long"
        entry_avg, exit_avg = buy_avg, sell_avg
        quantity = buy_qty
        entry_side_fills = buys

    gross_pnl = sell_value - buy_value
    net_pnl = gross_pnl - fees

    # Entry is the first fill, exit the last — correct duration for both
    # directions (a short enters on the sell and exits on the cover/buy).
    entry_ts = fills[0].filled_ts
    exit_ts = fills[-1].filled_ts
    duration_seconds = (exit_ts - entry_ts).total_seconds()

    # Union of attribution tags across the ENTRY-side fills, preserving
    # first-seen order and de-duplicating.
    entry_tags: list[str] = []
    for f in entry_side_fills:
        for tag in f.tags:
            if tag not in entry_tags:
                entry_tags.append(tag)

    return RoundTrip(
        symbol=symbol,
        side=side,
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        entry_avg_price=entry_avg,
        exit_avg_price=exit_avg,
        quantity=quantity,
        gross_pnl=gross_pnl,
        fees=fees,
        net_pnl=net_pnl,
        duration_seconds=duration_seconds,
        num_fills=len(fills),
        entry_tags=tuple(entry_tags),
    )


# ============================================================
# Returns and period inference
# ============================================================
def _equity_series(equity_curve: list[EquityPoint]) -> pd.Series:
    """Convert equity points to a pandas Series indexed by ts."""
    if not equity_curve:
        return pd.Series(dtype=float)
    return pd.Series(
        [float(ep.total_equity) for ep in equity_curve],
        index=pd.DatetimeIndex([ep.ts for ep in equity_curve]),
    )


def _infer_periods_per_year(equity: pd.Series) -> float:
    """Infer periods_per_year from median time-delta between equity points."""
    if len(equity) < 2:
        return 365.0
    deltas = equity.index.to_series().diff().dropna()
    if deltas.empty:
        return 365.0
    median_seconds = deltas.median().total_seconds()
    if median_seconds <= 0:
        return 365.0
    return SECONDS_PER_YEAR / median_seconds


# ============================================================
# Risk metrics
# ============================================================
def _sharpe(
    returns: pd.Series,
    periods_per_year: float,
    risk_free_annual: float = 0.0,
) -> float | None:
    """Annualized Sharpe. None if not computable."""
    if returns.empty:
        return None
    std = returns.std()
    if std == 0 or pd.isna(std):
        return None
    # Period-equivalent risk-free rate
    rf_period = (1 + risk_free_annual) ** (1 / periods_per_year) - 1
    excess = returns - rf_period
    return float(excess.mean() / std * math.sqrt(periods_per_year))


def _sortino(
    returns: pd.Series,
    periods_per_year: float,
    risk_free_annual: float = 0.0,
) -> float | None:
    """Annualized Sortino. None if no downside volatility."""
    if returns.empty:
        return None
    downside = returns[returns < 0]
    if downside.empty:
        return None
    downside_std = downside.std()
    if downside_std == 0 or pd.isna(downside_std):
        return None
    rf_period = (1 + risk_free_annual) ** (1 / periods_per_year) - 1
    excess = returns - rf_period
    return float(excess.mean() / downside_std * math.sqrt(periods_per_year))


def _max_drawdown(
    equity: pd.Series,
) -> tuple[float, datetime | None, datetime | None]:
    """Largest peak-to-trough decline as a fraction (e.g. -0.15 for -15%).

    Returns (max_dd, peak_ts, trough_ts). All zero / None if not computable.
    """
    if equity.empty or len(equity) < 2:
        return 0.0, None, None

    running_max = equity.cummax()
    # Guard against zero peaks (would never happen with positive starting cash)
    if (running_max == 0).any():
        return 0.0, None, None

    drawdown = (equity - running_max) / running_max
    if drawdown.empty:
        return 0.0, None, None

    trough_ts = drawdown.idxmin()
    max_dd = float(drawdown.loc[trough_ts])

    # Peak preceding this trough: last index where equity equaled running_max[trough_ts]
    peak_value = running_max.loc[trough_ts]
    before_trough = equity.loc[:trough_ts]
    peak_candidates = before_trough[before_trough == peak_value]
    peak_ts = peak_candidates.index[0] if not peak_candidates.empty else None

    return max_dd, peak_ts, trough_ts


# ============================================================
# Main entry point
# ============================================================
def compute_analytics(result: BacktestResult) -> BacktestAnalytics:
    """Compute the full analytics package over a BacktestResult."""
    closed, open_fills = _extract_round_trips(result.fills)
    equity = _equity_series(result.equity_curve)
    periods_per_year = _infer_periods_per_year(equity)
    returns = equity.pct_change().dropna() if not equity.empty else pd.Series(dtype=float)

    # ----- Return metrics -----
    total_return_pct = float(result.total_return_pct)

    annualized_return_pct: float | None = None
    if not equity.empty and len(equity) > 1:
        elapsed_seconds = (equity.index[-1] - equity.index[0]).total_seconds()
        if elapsed_seconds > 0:
            elapsed_years = elapsed_seconds / SECONDS_PER_YEAR
            total_return_fraction = total_return_pct / 100.0
            if (1 + total_return_fraction) > 0 and elapsed_years > 0:
                annualized_return_pct = (
                    ((1 + total_return_fraction) ** (1 / elapsed_years) - 1) * 100
                )

    # ----- Risk metrics -----
    sharpe = _sharpe(returns, periods_per_year)
    sortino = _sortino(returns, periods_per_year)
    max_dd, peak_ts, trough_ts = _max_drawdown(equity)
    max_dd_pct = max_dd * 100

    calmar: float | None = None
    if annualized_return_pct is not None and max_dd < 0:
        calmar = (annualized_return_pct / 100.0) / abs(max_dd)

    # A run with no COMPLETED round-trip has no realised track record. Any
    # Sharpe/Sortino/Calmar here is computed off the mark-to-market drift of a
    # position that never closed — reporting it as a risk-adjusted return is
    # misleading (e.g. "Sharpe 3.60" on a run with 0 trades). Suppress them so
    # the verdict reads as inconclusive rather than spuriously strong.
    if not closed:
        sharpe = None
        sortino = None
        calmar = None

    # ----- Trade metrics -----
    winners = [rt for rt in closed if rt.net_pnl > 0]
    losers = [rt for rt in closed if rt.net_pnl < 0]

    win_rate_pct: float | None = None
    if closed:
        win_rate_pct = len(winners) / len(closed) * 100

    avg_winner_pct: float | None = None
    if winners:
        ratios = [
            float(rt.net_pnl) / float(rt.entry_avg_price * rt.quantity)
            for rt in winners
            if rt.entry_avg_price * rt.quantity != 0
        ]
        if ratios:
            avg_winner_pct = (sum(ratios) / len(ratios)) * 100

    avg_loser_pct: float | None = None
    if losers:
        ratios = [
            float(rt.net_pnl) / float(rt.entry_avg_price * rt.quantity)
            for rt in losers
            if rt.entry_avg_price * rt.quantity != 0
        ]
        if ratios:
            avg_loser_pct = (sum(ratios) / len(ratios)) * 100

    gross_wins = sum(
        (rt.gross_pnl for rt in closed if rt.gross_pnl > 0),
        Decimal(0),
    )
    gross_losses = sum(
        (-rt.gross_pnl for rt in closed if rt.gross_pnl < 0),
        Decimal(0),
    )
    profit_factor: float | None = None
    if gross_losses > 0:
        profit_factor = float(gross_wins / gross_losses)

    avg_duration: float | None = None
    if closed:
        avg_duration = sum(rt.duration_seconds for rt in closed) / len(closed)

    # ----- Open trade count: roll up by symbol -----
    open_symbols: set[str] = {f.symbol for f in open_fills}
    num_open_trades = len(open_symbols)

    return BacktestAnalytics(
        total_return_pct=total_return_pct,
        annualized_return_pct=annualized_return_pct,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_peak_ts=peak_ts,
        max_drawdown_trough_ts=trough_ts,
        calmar_ratio=calmar,
        num_closed_trades=len(closed),
        num_open_trades=num_open_trades,
        win_rate_pct=win_rate_pct,
        avg_winner_pct=avg_winner_pct,
        avg_loser_pct=avg_loser_pct,
        profit_factor=profit_factor,
        avg_trade_duration_seconds=avg_duration,
        closed_round_trips=closed,
        periods_per_year=periods_per_year,
    )
