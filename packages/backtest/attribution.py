"""Performance attribution for a BacktestResult — the "why".

`compute_analytics()` (analytics.py) tells you *how well* a strategy did.
This module tells you *why*: it decomposes the realized P&L across two axes
and summarizes how each strategy signal/filter behaved.

  by_symbol  — P&L, win rate, and share of total profit for each traded
               symbol. Answers "which instruments made or lost the money".

  by_signal  — P&L, win rate, and trade count attributed to each signal the
               strategy emitted via ctx.signal(...). Answers "which entry
               condition actually pays" and, combined with the fire/block
               counts, "which filter needs tweaking". A round trip carrying
               multiple entry tags contributes its full P&L to EACH tag, so
               per-signal P&L can overlap and need not sum to the total — that
               overlap is itself informative (signals that co-fire on winners).

  signal_frequency — for every signal name, how many times it fired (passed)
               vs was blocked (passed=False). A filter that blocks almost
               everything, or never blocks anything, is a tuning target.

Attribution depends entirely on strategies calling ctx.signal(...). A strategy
that emits no signals still gets full by_symbol attribution; by_signal is then
empty and every trip is counted as `untagged`.

This is also the substrate for Phase 3 (ML/DRL): the per-bar SignalEvent log
(names, numeric values, pass/block outcomes) is a ready-made feature/label
store keyed by timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from packages.backtest.analytics import BacktestAnalytics, RoundTrip
from packages.backtest.types import BacktestResult, SignalEvent


# ============================================================
# Data classes
# ============================================================
@dataclass(frozen=True)
class SymbolAttribution:
    """Realized-P&L breakdown for one symbol over its closed round trips."""

    symbol: str
    num_trades: int
    wins: int
    losses: int
    win_rate_pct: float | None
    gross_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
    avg_net_pnl: Decimal
    # Share of the strategy's total net P&L (signed). None when total is zero.
    pct_of_total_net_pnl: float | None


@dataclass(frozen=True)
class SignalAttribution:
    """How one signal/filter behaved, and the P&L of the trades it tagged.

    `num_fired` / `num_blocked` come from the raw SignalEvent log (every bar
    the strategy evaluated the condition). `num_trades` and the P&L fields
    come only from closed round trips whose ENTRY carried this tag.
    """

    name: str
    # From the event log (per-bar evaluations):
    num_fired: int     # passed=True occurrences
    num_blocked: int   # passed=False occurrences
    # From tagged closed round trips:
    num_trades: int
    wins: int
    losses: int
    win_rate_pct: float | None
    net_pnl: Decimal
    avg_net_pnl: Decimal
    pct_of_total_net_pnl: float | None

    @property
    def num_evaluated(self) -> int:
        return self.num_fired + self.num_blocked

    @property
    def block_rate_pct(self) -> float | None:
        total = self.num_evaluated
        return (self.num_blocked / total * 100) if total else None


@dataclass(frozen=True)
class BacktestAttribution:
    """Full attribution decomposition over a backtest's closed round trips."""

    total_net_pnl: Decimal
    num_closed_trades: int
    by_symbol: list[SymbolAttribution]
    by_signal: list[SignalAttribution]
    # Trips whose entry carried no signal tag (strategy emitted no signal, or
    # only emitted passed=False events before entering). Counted so the user
    # knows how much P&L is unexplained by signals.
    untagged_trades: int = 0
    untagged_net_pnl: Decimal = Decimal(0)
    # Quick-look insights (names / symbols), None when there is nothing to rank.
    best_symbol: str | None = None
    worst_symbol: str | None = None
    best_signal: str | None = None
    worst_signal: str | None = None


# ============================================================
# Helpers
# ============================================================
def _pct_of(value: Decimal, total: Decimal) -> float | None:
    """Signed share of `total`, as a percentage. None when total is zero."""
    if total == 0:
        return None
    return float(value / total * 100)


def _win_rate(wins: int, num: int) -> float | None:
    return (wins / num * 100) if num else None


def _summarize_trips(trips: list[RoundTrip]) -> tuple[int, int, Decimal, Decimal, Decimal]:
    """(wins, losses, gross_pnl, fees, net_pnl) over a list of round trips."""
    wins = sum(1 for t in trips if t.net_pnl > 0)
    losses = sum(1 for t in trips if t.net_pnl < 0)
    gross = sum((t.gross_pnl for t in trips), Decimal(0))
    fees = sum((t.fees for t in trips), Decimal(0))
    net = sum((t.net_pnl for t in trips), Decimal(0))
    return wins, losses, gross, fees, net


# ============================================================
# Main entry point
# ============================================================
def compute_attribution(
    result: BacktestResult,
    analytics: BacktestAnalytics,
) -> BacktestAttribution:
    """Decompose realized P&L by symbol and by signal.

    `analytics` supplies the already-extracted closed round trips (so we do
    not re-pair fills); `result.signal_events` supplies the raw per-bar
    fire/block log for signal frequency.
    """
    trips = analytics.closed_round_trips
    total_net = sum((t.net_pnl for t in trips), Decimal(0))

    by_symbol = _attribute_by_symbol(trips, total_net)
    by_signal = _attribute_by_signal(trips, result.signal_events, total_net)

    untagged = [t for t in trips if not t.entry_tags]
    _, _, _, _, untagged_net = _summarize_trips(untagged)

    return BacktestAttribution(
        total_net_pnl=total_net,
        num_closed_trades=len(trips),
        by_symbol=by_symbol,
        by_signal=by_signal,
        untagged_trades=len(untagged),
        untagged_net_pnl=untagged_net,
        best_symbol=by_symbol[0].symbol if by_symbol else None,
        worst_symbol=by_symbol[-1].symbol if by_symbol else None,
        best_signal=by_signal[0].name if by_signal else None,
        worst_signal=by_signal[-1].name if by_signal else None,
    )


# ============================================================
# Serialization (for JSONB persistence / API response)
# ============================================================
def attribution_to_dict(attr: BacktestAttribution) -> dict:
    """Render a BacktestAttribution as a JSON-serializable dict.

    Money fields (Decimal) are emitted as strings to avoid float precision
    loss; ratios/percentages stay as floats (or null). The shape mirrors the
    dataclasses field-for-field and is what the detail API returns verbatim.
    """

    def _sym(s: SymbolAttribution) -> dict:
        return {
            "symbol": s.symbol,
            "num_trades": s.num_trades,
            "wins": s.wins,
            "losses": s.losses,
            "win_rate_pct": s.win_rate_pct,
            "gross_pnl": str(s.gross_pnl),
            "fees": str(s.fees),
            "net_pnl": str(s.net_pnl),
            "avg_net_pnl": str(s.avg_net_pnl),
            "pct_of_total_net_pnl": s.pct_of_total_net_pnl,
        }

    def _sig(s: SignalAttribution) -> dict:
        return {
            "name": s.name,
            "num_fired": s.num_fired,
            "num_blocked": s.num_blocked,
            "num_evaluated": s.num_evaluated,
            "block_rate_pct": s.block_rate_pct,
            "num_trades": s.num_trades,
            "wins": s.wins,
            "losses": s.losses,
            "win_rate_pct": s.win_rate_pct,
            "net_pnl": str(s.net_pnl),
            "avg_net_pnl": str(s.avg_net_pnl),
            "pct_of_total_net_pnl": s.pct_of_total_net_pnl,
        }

    return {
        "total_net_pnl": str(attr.total_net_pnl),
        "num_closed_trades": attr.num_closed_trades,
        "by_symbol": [_sym(s) for s in attr.by_symbol],
        "by_signal": [_sig(s) for s in attr.by_signal],
        "untagged_trades": attr.untagged_trades,
        "untagged_net_pnl": str(attr.untagged_net_pnl),
        "best_symbol": attr.best_symbol,
        "worst_symbol": attr.worst_symbol,
        "best_signal": attr.best_signal,
        "worst_signal": attr.worst_signal,
    }


def _attribute_by_symbol(
    trips: list[RoundTrip],
    total_net: Decimal,
) -> list[SymbolAttribution]:
    by_sym: dict[str, list[RoundTrip]] = {}
    for t in trips:
        by_sym.setdefault(t.symbol, []).append(t)

    out: list[SymbolAttribution] = []
    for symbol, sym_trips in by_sym.items():
        wins, losses, gross, fees, net = _summarize_trips(sym_trips)
        n = len(sym_trips)
        out.append(
            SymbolAttribution(
                symbol=symbol,
                num_trades=n,
                wins=wins,
                losses=losses,
                win_rate_pct=_win_rate(wins, n),
                gross_pnl=gross,
                fees=fees,
                net_pnl=net,
                avg_net_pnl=(net / n) if n else Decimal(0),
                pct_of_total_net_pnl=_pct_of(net, total_net),
            )
        )
    # Most profitable first; ties broken by trade count for stability.
    out.sort(key=lambda s: (s.net_pnl, s.num_trades), reverse=True)
    return out


def _attribute_by_signal(
    trips: list[RoundTrip],
    events: list[SignalEvent],
    total_net: Decimal,
) -> list[SignalAttribution]:
    # Fire/block counts from the raw event log (covers signals that never
    # produced a trade, e.g. pure blocking filters).
    fired: dict[str, int] = {}
    blocked: dict[str, int] = {}
    for ev in events:
        bucket = fired if ev.passed else blocked
        bucket[ev.name] = bucket.get(ev.name, 0) + 1

    # Tagged trips per signal name (a trip lands in every one of its tags).
    by_tag: dict[str, list[RoundTrip]] = {}
    for t in trips:
        for tag in t.entry_tags:
            by_tag.setdefault(tag, []).append(t)

    names = set(fired) | set(blocked) | set(by_tag)
    out: list[SignalAttribution] = []
    for name in names:
        tagged = by_tag.get(name, [])
        wins, losses, _gross, _fees, net = _summarize_trips(tagged)
        n = len(tagged)
        out.append(
            SignalAttribution(
                name=name,
                num_fired=fired.get(name, 0),
                num_blocked=blocked.get(name, 0),
                num_trades=n,
                wins=wins,
                losses=losses,
                win_rate_pct=_win_rate(wins, n),
                net_pnl=net,
                avg_net_pnl=(net / n) if n else Decimal(0),
                pct_of_total_net_pnl=_pct_of(net, total_net),
            )
        )
    # Best-paying signal first; signals that produced no trades sink to the
    # bottom (net 0) but remain visible for frequency analysis.
    out.sort(key=lambda s: (s.net_pnl, s.num_trades), reverse=True)
    return out
