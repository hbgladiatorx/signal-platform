"""External-strategy intake for the Referee certification flow.

Takes an outside user's evidence in one of the formats the platform already
understands — a trade-log CSV, an equity-curve CSV, or a returns series — and
normalizes it to a single net-of-cost per-observation return series that the
unchanged gauntlet (referee.stats / referee.verdict) can grade.

Two integrity duties live here, and neither is allowed to soften:

  1. DATA INTEGRITY. The same checks we run on our own data — gaps, bad ticks,
     stale forward-fills, look-ahead tells — applied to the submission. A
     submission that fails is UNVERIFIABLE with a reason. Bad data never
     silently becomes a clean cert.

  2. THE TRIAL-COUNT FLOOR. The one way an outsider games the cert is submitting
     their single best strategy while hiding how many they tried. We require a
     declared trial count, mark it self_declared, estimate a provable floor from
     the submission metadata, and deflate at max(declared, floor). Honesty is
     forced onto the visible record.

Pure numpy/pandas; runs in the same worker image as the rest of referee/.
No execution, no broker, no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
import pandas as pd

# ----- integrity thresholds (frozen; conservative; never relaxed per user) -----
MIN_OBS = 60                 # < 60 observations => too short a track record to test
MAX_PLAUSIBLE_ABS_RET = 10.0  # a single +1000% period => data error, not a trade
FLAG_ABS_RET = 0.50          # 50%+ in one period => flagged (could be legit for some assets)
STALE_RUN_FRAC = 0.10        # identical consecutive returns over >10% of series => stale fill
LOOKAHEAD_MAX_ANN_SHARPE = 12.0   # ann Sharpe above this from a returns series => look-ahead tell
LOOKAHEAD_MIN_NEG_FRAC = 0.01     # < 1% losing periods over a long series => look-ahead tell
GAP_FATAL_FRAC = 0.05        # > 5% of intervals are gaps => calendar too broken to trust


class SubmissionError(ValueError):
    """Raised when a submission cannot even be parsed into a returns series."""


@dataclass
class Submission:
    """Normalized submission ready for the gauntlet."""
    returns: np.ndarray                 # net-of-cost per-observation returns (decimal)
    timestamps: pd.DatetimeIndex | None  # None for trade-logs with no timestamp
    fmt: str                            # "trade_log" | "equity_curve" | "returns"
    n_obs: int
    cost_bps: float                     # declared round-trip cost (label / applied)
    cost_applied: bool                  # True if we deducted it (gross submission)
    declared_trials: int
    periods_per_year: float
    raw_cols: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Per-return boolean mask, aligned to `returns`: True where the strategy held
    # a position over that interval, False where it was out of the market. None
    # when the submission carried no exposure/position column. When present, the
    # integrity pass treats no-position flat stretches as structurally flat
    # (strategy out of market) rather than stale/forward-filled data, and applies
    # the min-observations floor to the active (in-position) count. Grading is
    # unchanged — the gauntlet still sees the full per-bar series.
    in_position: np.ndarray | None = None


# ------------------------------------------------------------------ parsing
def _find(cols, *cands):
    low = {c.lower().strip(): c for c in cols}
    for cand in cands:
        if cand in low:
            return low[cand]
    return None


def _detect_format(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    if _find(cols, "equity", "nav", "balance", "account_value", "portfolio_value"):
        return "equity_curve"
    if _find(cols, "return", "ret", "r", "pnl_pct", "return_pct", "daily_return"):
        # a trade log usually also carries an entry/exit price or trade id
        if _find(cols, "trade_id", "entry_time", "exit_time", "entry_price", "exit_price"):
            return "trade_log"
        return "returns"
    if _find(cols, "pnl", "profit", "pl") and _find(cols, "trade_id", "exit_time", "entry_time"):
        return "trade_log"
    raise SubmissionError(
        f"could not detect format from columns {cols}; expected an equity column, "
        "a return column, or a trade-log pnl/return column")


def _timestamps(df: pd.DataFrame):
    col = _find(df.columns, "timestamp", "date", "datetime", "time", "exit_time", "close_time")
    if col is None:
        return None, None
    ts = pd.DatetimeIndex(pd.to_datetime(df[col], utc=True, errors="coerce"))
    return ts, col


def _maybe_percent(vals: np.ndarray, notes: list[str], what: str) -> np.ndarray:
    """Heuristic: if returns are clearly in percent (typical magnitudes >~1.5),
    convert to decimal. Recorded as a note so the conversion is on the record."""
    finite = vals[np.isfinite(vals)]
    if finite.size and np.nanmedian(np.abs(finite)) > 1.5:
        notes.append(f"{what}: values look like percent (median |x|>1.5); divided by 100")
        return vals / 100.0
    return vals


def parse_submission(path: str, *, fmt: str | None = None, cost_bps: float,
                     declared_trials: int, returns_are_gross: bool = False,
                     periods_per_year: float | None = None) -> Submission:
    """Read a CSV submission and normalize to net per-observation returns."""
    if declared_trials < 1:
        raise SubmissionError("declared_trials must be >= 1 (declare 1 if no search was run)")
    try:
        df = pd.read_csv(path)
    except Exception as e:  # noqa: BLE001
        raise SubmissionError(f"cannot read CSV: {e}") from e
    if df.empty:
        raise SubmissionError("submission is empty")
    df.columns = [str(c) for c in df.columns]
    fmt = fmt or _detect_format(df)
    notes: list[str] = []
    ts, ts_col = _timestamps(df)
    if ts is not None and ts.isna().any():
        notes.append("some timestamps unparseable; rows kept in file order")
        ts = None

    # Optional exposure/position column. The platform's backtest equity curve
    # carries `positions_value` per bar; when present it lets the integrity pass
    # tell "flat because out of the market" (positions_value == 0) from "flat
    # because forward-filled data". Absent it, behaviour is unchanged.
    exp_col = _find(df.columns, "positions_value", "position_value", "exposure",
                    "in_position", "net_position", "position", "positions",
                    "units", "qty", "shares", "net_qty")
    pos_raw = (pd.to_numeric(df[exp_col], errors="coerce").to_numpy(float)
               if exp_col is not None else None)
    in_position: np.ndarray | None = None

    cost_frac = cost_bps / 1e4
    cost_applied = False

    if fmt == "equity_curve":
        ecol = _find(df.columns, "equity", "nav", "balance", "account_value", "portfolio_value")
        eq = pd.to_numeric(df[ecol], errors="coerce").to_numpy(float)
        if ts is not None:
            order = np.argsort(ts.values, kind="stable")
            eq = eq[order]; ts = ts[order]
            if pos_raw is not None:
                pos_raw = pos_raw[order]
        if returns_are_gross:
            raise SubmissionError(
                "cannot net a gross equity curve (no turnover information); submit net "
                "equity, or a trade log if you want round-trip cost applied")
        with np.errstate(divide="ignore", invalid="ignore"):
            rets = np.diff(eq) / eq[:-1]
        ts = ts[1:] if ts is not None else None
        if pos_raw is not None:
            # A per-bar return reflects the position held over [t-1, t]; mark it
            # active if there was exposure at either endpoint (captures entry and
            # exit bars). NaN exposure -> treated as flat.
            held = np.nan_to_num(pos_raw) != 0
            in_position = held[:-1] | held[1:]

    elif fmt == "returns":
        rcol = _find(df.columns, "return", "ret", "r", "daily_return", "return_pct", "pnl_pct")
        rets = pd.to_numeric(df[rcol], errors="coerce").to_numpy(float)
        if ts is not None:
            order = np.argsort(ts.values, kind="stable")
            rets = rets[order]; ts = ts[order]
            if pos_raw is not None:
                pos_raw = pos_raw[order]
        if pos_raw is not None:
            in_position = np.nan_to_num(pos_raw) != 0
        rets = _maybe_percent(rets, notes, "returns")
        if returns_are_gross:
            raise SubmissionError(
                "cannot net a gross returns series (no turnover information); submit net "
                "returns, or a trade log if you want round-trip cost applied")

    elif fmt == "trade_log":
        rcol = _find(df.columns, "return", "ret", "pnl_pct", "return_pct")
        if rcol is not None:
            rets = pd.to_numeric(df[rcol], errors="coerce").to_numpy(float)
            rets = _maybe_percent(rets, notes, "trade returns")
        else:
            # pnl + capital -> per-trade return
            pcol = _find(df.columns, "pnl", "profit", "pl")
            ccol = _find(df.columns, "capital", "equity_before", "notional", "position_size")
            if pcol is None or ccol is None:
                raise SubmissionError(
                    "trade log needs a per-trade return column, or absolute pnl plus a "
                    "capital/notional column to derive returns")
            pnl = pd.to_numeric(df[pcol], errors="coerce").to_numpy(float)
            cap = pd.to_numeric(df[ccol], errors="coerce").to_numpy(float)
            with np.errstate(divide="ignore", invalid="ignore"):
                rets = pnl / cap
        if ts is not None:
            order = np.argsort(ts.values, kind="stable")
            rets = rets[order]; ts = ts[order]
        if returns_are_gross:
            rets = rets - cost_frac          # one round trip per trade
            cost_applied = True
            notes.append(f"applied {cost_bps:.1f}bps round-trip cost per trade (gross submission)")
    else:
        raise SubmissionError(f"unknown format {fmt!r}")

    rets = np.asarray(rets, dtype=float)
    if rets.size == 0:
        raise SubmissionError("no returns could be derived from the submission")

    # Align the exposure mask to the returns; drop it on any length mismatch so a
    # malformed column can never silently corrupt grading.
    if in_position is not None:
        in_position = np.asarray(in_position, dtype=bool)
        if in_position.size != rets.size:
            in_position = None
        else:
            n_flat = int((~in_position).sum())
            if n_flat:
                notes.append(
                    f"exposure column '{exp_col}': {n_flat} no-position bar(s) "
                    f"excluded from the stale-fill test; min-obs floor applied to "
                    f"{int(in_position.sum())} active observation(s)")

    # infer periods/year from the actual sample density (honest, asset-agnostic)
    if periods_per_year is None:
        if ts is not None and len(ts) >= 3:
            span_years = max((ts[-1] - ts[0]).total_seconds() / (365.25 * 86400), 1e-9)
            periods_per_year = float(len(rets) / span_years)
        else:
            periods_per_year = 252.0
            notes.append("no timestamps; assumed 252 periods/year for annualization only")

    return Submission(returns=rets, timestamps=ts, fmt=fmt, n_obs=int(rets.size),
                      cost_bps=float(cost_bps), cost_applied=cost_applied,
                      declared_trials=int(declared_trials),
                      periods_per_year=float(periods_per_year),
                      raw_cols=list(df.columns), notes=notes,
                      in_position=in_position)


# --------------------------------------------------------------- integrity
def _longest_identical_run(vals: np.ndarray, active: np.ndarray | None) -> int:
    """Longest run of identical consecutive returns.

    When `active` is given, no-position bars BREAK and are excluded from runs, so
    a legit idle flat stretch (strategy out of the market) is never counted as
    stale — but a forward-filled run WHILE HOLDING still is. Matches the original
    run semantics (k identical consecutive -> run length k) on the in-scope bars.
    """
    max_run = 0
    run = 0
    prev = None
    for i in range(vals.size):
        if active is not None and not active[i]:
            run = 0
            prev = None
            continue
        v = vals[i]
        if prev is not None and v == prev:
            run += 1
        else:
            run = 1
        prev = v
        if run > max_run:
            max_run = run
    return max_run


def check_integrity(sub: Submission) -> dict:
    """Run the same family of integrity checks we run on our own data.

    Returns {status: CLEAN|FLAG|UNVERIFIABLE, reasons:[...], flags:[...], metrics:{}}.
    UNVERIFIABLE is a disqualifying integrity failure, never a pass.
    """
    r = sub.returns
    reasons: list[str] = []   # disqualifying
    flags: list[str] = []     # noted, not disqualifying
    m: dict = {}

    # --- finiteness / size ---
    n_nonfinite = int((~np.isfinite(r)).sum())
    m["n_obs"] = int(r.size)
    m["n_nonfinite"] = n_nonfinite
    if n_nonfinite:
        reasons.append(f"{n_nonfinite} non-finite return(s) (NaN/inf) — broken series")

    fin = np.isfinite(r)
    rf = r[fin]
    # Exposure-aware scope: when the submission carried a position column, the
    # ACTIVE (in-position) bars are the right unit for the min-obs floor and the
    # flat-run / look-ahead tells — no-position bars are structurally flat, not
    # stale. Without exposure info every finite bar is in scope (unchanged).
    active = (sub.in_position & fin) if (
        sub.in_position is not None and sub.in_position.shape == r.shape) else None
    ev = r[active] if active is not None else rf      # evaluation series
    n_eval = int(ev.size)
    if active is not None:
        m["n_active_obs"] = int(active.sum())

    # --- min observations (applied to the active unit when exposure is known) ---
    if active is not None:
        if n_eval < MIN_OBS:
            reasons.append(f"only {n_eval} active (in-position) observations "
                           f"(< {MIN_OBS}); too few trades / held bars to grade")
    elif r.size < MIN_OBS:
        reasons.append(f"only {r.size} observations (< {MIN_OBS}); track record too short to test")

    if rf.size:
        # --- bad ticks (any bar, in or out of position) ---
        max_abs = float(np.max(np.abs(rf)))
        m["max_abs_return"] = max_abs
        if max_abs > MAX_PLAUSIBLE_ABS_RET:
            reasons.append(f"a single-period return of {max_abs:.1f}x — data error, not a trade")
        n_flag = int((np.abs(rf) > FLAG_ABS_RET).sum())
        if n_flag:
            flags.append(f"{n_flag} period(s) with |return| > {FLAG_ABS_RET:.0%}")

        # --- stale forward-fill: identical consecutive returns ---
        # No-position bars are excluded as structurally flat; a forward-filled run
        # WHILE HOLDING — or any submission with no exposure column — still trips.
        if active is not None:
            max_run = _longest_identical_run(r, active)
            denom = n_eval
            scope = "active "
        else:
            max_run = _longest_identical_run(rf, None)
            denom = rf.size
            scope = ""
        m["max_identical_run"] = max_run
        if max_run > max(STALE_RUN_FRAC * denom, 10):
            reasons.append(f"{max_run} identical consecutive returns "
                           f"(> {STALE_RUN_FRAC:.0%} of {scope}series) — stale / forward-filled")
        elif max_run > 10:
            flags.append(f"longest identical-return run = {max_run}")

        # --- look-ahead tells (on the active unit when exposure is known) ---
        sd = ev.std(ddof=1) if n_eval >= 2 else 0.0
        ann_sh = float(ev.mean() / sd * np.sqrt(sub.periods_per_year)) if sd > 0 else 0.0
        neg_frac = float((ev < 0).mean()) if n_eval else 0.0
        m["ann_sharpe_naive"] = ann_sh
        m["neg_period_frac"] = neg_frac
        if ann_sh > LOOKAHEAD_MAX_ANN_SHARPE:
            reasons.append(f"annualized Sharpe {ann_sh:.1f} exceeds {LOOKAHEAD_MAX_ANN_SHARPE:.0f} "
                           "— implausibly smooth, a look-ahead/curve-fit tell")
        if n_eval >= 200 and neg_frac < LOOKAHEAD_MIN_NEG_FRAC:
            reasons.append(f"only {neg_frac:.1%} losing periods over {n_eval} obs "
                           "— a real strategy loses sometimes; look-ahead tell")

    # --- timestamp continuity / gaps ---
    if sub.timestamps is not None and len(sub.timestamps) >= 3:
        ts = sub.timestamps
        tv = ts.asi8
        dups = int((np.diff(tv) == 0).sum())
        nonmono = int((np.diff(tv) < 0).sum())
        m["duplicate_ts"] = dups
        m["non_monotonic_ts"] = nonmono
        if dups:
            reasons.append(f"{dups} duplicate timestamp(s)")
        if nonmono:
            reasons.append(f"{nonmono} non-monotonic timestamp(s) — series not in time order")
        deltas = np.diff(tv).astype(float)
        deltas = deltas[deltas > 0]
        if deltas.size:
            # cadence-aware: tolerate the modal spacing AND regular weekend gaps
            # (a business-day calendar alternates 1-day and 3-day steps — neither is
            # a hole). A genuine gap is a step well beyond the normal cadence.
            vals, counts = np.unique(deltas, return_counts=True)
            modal = float(vals[int(np.argmax(counts))])
            med = float(np.median(deltas))
            thresh = max(4.0 * modal, 3.0 * med)   # unit-internal-consistent
            gaps = int((deltas > thresh).sum())
            # asi8 ints are in the index's resolution (ns/us/ms/s in pandas 2/3);
            # convert to days for display using that unit.
            sec_per_unit = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}
            spu = sec_per_unit.get(getattr(ts, "unit", "ns"), 1e-9)
            m["modal_spacing_days"] = round(modal * spu / 86400.0, 4)
            m["gap_count"] = gaps
            m["gap_frac"] = gaps / deltas.size
            if gaps / deltas.size > GAP_FATAL_FRAC:
                reasons.append(f"{gaps} calendar gaps ({gaps/deltas.size:.0%} of intervals) "
                               "— series too discontinuous to trust")
            elif gaps:
                flags.append(f"{gaps} calendar gap(s) beyond normal cadence")

    status = "UNVERIFIABLE" if reasons else ("FLAG" if flags else "CLEAN")
    return {"status": status, "reasons": reasons, "flags": flags, "metrics": m}


# ------------------------------------------------------- trial-count floor
def estimate_trial_floor(sub: Submission, *, n_config_series: int = 0,
                         declared_grid_size: int | None = None) -> dict:
    """A provable LOWER BOUND on trials from submission metadata.

    We cannot read a searcher's mind from a single returns series, so the floor is
    only as strong as the evidence supplied: the number of config series actually
    submitted, or a declared parameter-grid size. The deflation then uses
    max(declared, floor); if declared < floor the submitter under-declared and we
    say so on the record.
    """
    floor = 1
    basis = ["single submitted series (no provable search from one series)"]
    if n_config_series and n_config_series > floor:
        floor = int(n_config_series)
        basis = [f"{n_config_series} config series submitted in the matrix"]
    if declared_grid_size and declared_grid_size > floor:
        floor = int(declared_grid_size)
        basis = [f"declared parameter-grid size {declared_grid_size}"]
    n_used = max(sub.declared_trials, floor)
    return {"declared_trials": sub.declared_trials, "self_declared": True,
            "provable_floor": floor, "floor_basis": basis,
            "n_trials_used": int(n_used),
            "declared_below_floor": bool(sub.declared_trials < floor)}
