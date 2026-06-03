"""Feature/label store: turn a backtest into a labeled training matrix.

Each closed round trip becomes one training example:

  * **Label** — was the trip profitable (``net_pnl > 0``)? Also keep the raw
    ``net_pnl`` for regression use.
  * **Features** — built only from information available *at entry* (no
    look-ahead): for every signal in the run's vocabulary, an ``active`` flag
    (was this signal one of the entry tags) and its numeric ``value`` at the
    decision bar, plus a small count of how many signals co-fired.

Linking values to a trip
------------------------
``RoundTrip.entry_tags`` gives the *names* of the passed signals that tagged
the entry, but not their numeric readings — those live in the ``SignalEvent``
log, keyed by the *decision* bar (the bar whose order later filled). The fill
timestamp (``entry_ts``) is therefore strictly after the signal's ``ts``, so
we join each entry tag to the most recent passed ``SignalEvent`` of that name
at-or-before the entry, preferring a symbol-specific event over a global one.
In the common case (signal fires on bar T, order fills on T+1, no intervening
re-fire) this recovers the exact reading; the active flag from ``entry_tags``
is authoritative regardless of whether a value is found.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from packages.backtest.analytics import BacktestAnalytics, RoundTrip
from packages.backtest.types import BacktestResult, SignalEvent

# A trip carrying fewer than this many co-firing… nothing special; this is the
# count feature's name only. Kept as a constant so the model module and tests
# can reference the exact feature name without string drift.
COUNT_FEATURE = "n_active_signals"


@dataclass(frozen=True)
class TrainingDataset:
    """A labeled feature matrix extracted from one backtest.

    ``X`` is ``(n_samples, n_features)`` float; ``feature_names`` labels its
    columns. ``y_class`` is the 0/1 profitability label; ``y_pnl`` the signed
    net P&L. ``row_symbols`` records each example's symbol (for reference, not
    a feature). ``signal_names`` is the sorted signal vocabulary the feature
    columns were built from.
    """

    feature_names: list[str]
    X: np.ndarray
    y_class: np.ndarray
    y_pnl: np.ndarray
    row_symbols: list[str]
    signal_names: list[str]

    @property
    def n_samples(self) -> int:
        return int(self.X.shape[0])

    @property
    def n_features(self) -> int:
        return int(self.X.shape[1])

    @property
    def base_profit_rate(self) -> float:
        """Fraction of trips that were profitable (the no-skill baseline)."""
        return float(self.y_class.mean()) if self.n_samples else 0.0

    def active_column_for(self, signal_name: str) -> int | None:
        """Index of a signal's ``active`` feature column, or None."""
        col = f"sig::{signal_name}::active"
        return self.feature_names.index(col) if col in self.feature_names else None


@dataclass(frozen=True)
class FeatureSample:
    """One closed round trip as a portable, backtest-independent training row.

    Unlike a row of a ``TrainingDataset`` (which is tied to that run's feature
    column layout), a ``FeatureSample`` carries only the signals that were
    *active at entry* mapped to their numeric reading (or None). This is the
    unit that persists across backtests; ``samples_to_dataset`` later stitches
    many of them — possibly with different signal vocabularies — into one
    unified matrix for cross-backtest training.
    """

    symbol: str
    entry_ts: datetime
    profitable: bool
    net_pnl: float
    signal_values: dict[str, float | None]


def _signal_value_lookup(
    events: list[SignalEvent],
) -> dict[tuple[str, str | None], list[tuple[datetime, float]]]:
    """Index passed signal readings by (name, symbol), each time-sorted.

    Only ``passed=True`` events with a non-None numeric value are indexed —
    those are the readings a trip's entry can carry. ``symbol`` is kept as-is
    (None = a global signal) so the join can prefer symbol-specific readings.
    """
    out: dict[tuple[str, str | None], list[tuple[datetime, float]]] = {}
    for ev in events:
        if not ev.passed or ev.value is None:
            continue
        out.setdefault((ev.name, ev.symbol), []).append((ev.ts, float(ev.value)))
    for series in out.values():
        series.sort(key=lambda p: p[0])
    return out


def _latest_value_at_or_before(
    series: list[tuple[datetime, float]], cutoff: datetime
) -> float | None:
    """Most recent reading with ts <= cutoff (series must be time-sorted)."""
    found: float | None = None
    for ts, value in series:
        if ts <= cutoff:
            found = value
        else:
            break
    return found


def _entry_value(
    lookup: dict[tuple[str, str | None], list[tuple[datetime, float]]],
    name: str,
    symbol: str,
    entry_ts: datetime,
) -> float | None:
    """Resolve a signal's numeric reading for a trip's entry.

    Prefer a symbol-specific reading; fall back to a global (symbol=None) one.
    """
    for key in ((name, symbol), (name, None)):
        series = lookup.get(key)
        if series:
            value = _latest_value_at_or_before(series, entry_ts)
            if value is not None:
                return value
    return None


def _signal_vocabulary(
    trips: list[RoundTrip], events: list[SignalEvent]
) -> list[str]:
    """Sorted union of every signal name that tagged a trip or fired passed.

    Restricting columns to signals that actually *tagged* entries would drop
    pure blocking filters; including every passed signal keeps the feature
    space stable across runs of the same strategy. We use entry tags (the
    causal link to outcomes) plus passed events.
    """
    names: set[str] = set()
    for t in trips:
        names.update(t.entry_tags)
    for ev in events:
        if ev.passed:
            names.add(ev.name)
    return sorted(names)


def build_dataset(
    result: BacktestResult,
    analytics: BacktestAnalytics,
) -> TrainingDataset:
    """Extract a labeled feature matrix from a completed backtest.

    Returns an empty (0-row) dataset when there are no closed round trips or
    the strategy emitted no signals — callers should treat that as "nothing to
    learn" rather than an error.
    """
    trips = analytics.closed_round_trips
    signal_names = _signal_vocabulary(trips, result.signal_events)

    # Feature columns: per signal an active flag + numeric value, then a count.
    feature_names: list[str] = []
    for name in signal_names:
        feature_names.append(f"sig::{name}::active")
        feature_names.append(f"sig::{name}::value")
    feature_names.append(COUNT_FEATURE)

    # No signals (or no trips) → nothing to learn; return an empty matrix that
    # still carries the (possibly empty) column layout.
    if not signal_names or not trips:
        return TrainingDataset(
            feature_names=feature_names,
            X=np.zeros((0, len(feature_names)), dtype=float),
            y_class=np.zeros((0,), dtype=int),
            y_pnl=np.zeros((0,), dtype=float),
            row_symbols=[],
            signal_names=signal_names,
        )

    lookup = _signal_value_lookup(result.signal_events)
    name_index = {name: i for i, name in enumerate(signal_names)}

    rows: list[np.ndarray] = []
    y_class: list[int] = []
    y_pnl: list[float] = []
    row_symbols: list[str] = []

    for t in trips:
        vec = np.zeros(len(feature_names), dtype=float)
        active_tags = [n for n in t.entry_tags if n in name_index]
        for name in active_tags:
            base = name_index[name] * 2
            vec[base] = 1.0  # active flag
            value = _entry_value(lookup, name, t.symbol, t.entry_ts)
            if value is not None:
                vec[base + 1] = value  # numeric reading
        vec[-1] = float(len(active_tags))  # n_active_signals

        rows.append(vec)
        y_class.append(1 if t.net_pnl > 0 else 0)
        y_pnl.append(float(t.net_pnl))
        row_symbols.append(t.symbol)

    return TrainingDataset(
        feature_names=feature_names,
        X=np.vstack(rows),
        y_class=np.asarray(y_class, dtype=int),
        y_pnl=np.asarray(y_pnl, dtype=float),
        row_symbols=row_symbols,
        signal_names=signal_names,
    )


# ============================================================
# Cross-backtest store: portable samples ↔ unified dataset
# ============================================================
def extract_samples(
    result: BacktestResult,
    analytics: BacktestAnalytics,
) -> list[FeatureSample]:
    """One ``FeatureSample`` per closed round trip, for the persistent store.

    Uses the same leak-free entry-time join as ``build_dataset`` to recover
    each entry signal's decision-bar reading. Trips with no entry tags still
    produce a sample (with an empty ``signal_values``) so the label count and
    base rate stay honest across the aggregate.
    """
    lookup = _signal_value_lookup(result.signal_events)
    samples: list[FeatureSample] = []
    for t in analytics.closed_round_trips:
        signal_values = {
            name: _entry_value(lookup, name, t.symbol, t.entry_ts)
            for name in t.entry_tags
        }
        samples.append(
            FeatureSample(
                symbol=t.symbol,
                entry_ts=t.entry_ts,
                profitable=t.net_pnl > 0,
                net_pnl=float(t.net_pnl),
                signal_values=signal_values,
            )
        )
    return samples


def samples_to_dataset(samples: Iterable[FeatureSample]) -> TrainingDataset:
    """Stitch portable samples into one unified ``TrainingDataset``.

    The feature vocabulary is the sorted union of every signal seen across the
    samples, so runs that fired different signals still share a coherent column
    layout (a signal absent from a sample is simply inactive there). The result
    feeds ``train_signal_edge_model`` unchanged — that is the whole point of the
    cross-backtest store.
    """
    samples = list(samples)
    signal_names = sorted(
        {name for s in samples for name in s.signal_values}
    )

    feature_names: list[str] = []
    for name in signal_names:
        feature_names.append(f"sig::{name}::active")
        feature_names.append(f"sig::{name}::value")
    feature_names.append(COUNT_FEATURE)

    if not samples:
        return TrainingDataset(
            feature_names=feature_names,
            X=np.zeros((0, len(feature_names)), dtype=float),
            y_class=np.zeros((0,), dtype=int),
            y_pnl=np.zeros((0,), dtype=float),
            row_symbols=[],
            signal_names=signal_names,
        )

    name_index = {name: i for i, name in enumerate(signal_names)}
    rows: list[np.ndarray] = []
    y_class: list[int] = []
    y_pnl: list[float] = []
    row_symbols: list[str] = []

    for s in samples:
        vec = np.zeros(len(feature_names), dtype=float)
        active = [n for n in s.signal_values if n in name_index]
        for name in active:
            base = name_index[name] * 2
            vec[base] = 1.0
            value = s.signal_values[name]
            if value is not None:
                vec[base + 1] = float(value)
        vec[-1] = float(len(active))
        rows.append(vec)
        y_class.append(1 if s.profitable else 0)
        y_pnl.append(float(s.net_pnl))
        row_symbols.append(s.symbol)

    return TrainingDataset(
        feature_names=feature_names,
        X=np.vstack(rows),
        y_class=np.asarray(y_class, dtype=int),
        y_pnl=np.asarray(y_pnl, dtype=float),
        row_symbols=row_symbols,
        signal_names=signal_names,
    )
