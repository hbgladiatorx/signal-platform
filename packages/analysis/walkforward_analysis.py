"""Deterministic walk-forward (validation / OOS) verdict.

The walk-forward stage already COMPUTES the honest out-of-sample numbers —
average test Sharpe, train-vs-test overfit drop, the share of windows that held
up, average test return. Until now it dead-ended there: a wall of metrics with
no plain call, no statement of what failed, and no path back into the loop.

`analyze_walkforward` adds a legible verdict ON TOP of those already-computed
numbers. It changes NO validation math: it reads the metrics the engine stored
and renders them, exactly as `analyze_backtest` does for the backtest stage.

It speaks the referee gauntlet's language so the platform has one verdict
vocabulary end to end:

  * verdict   ∈ {DEPLOY, HOLD_CONDITIONAL, REJECT, UNVERIFIABLE}  (referee call)
  * findings  use the referee failure-cluster words (single_regime, cost-wall,
              overfit/deflation_collapse, no_signal …) as the ranked what-to-fix
  * next_action is the path back — a concrete, machine-readable step that returns
              the user toward editing / rebuilding (or, on a pass, deploying).

Output shape (JSON-serializable), aligned with `analyze_backtest` so the
frontend renders both stages uniformly::

    {
      "schema": "studio.validation/1",
      "verdict": "DEPLOY" | "HOLD_CONDITIONAL" | "REJECT" | "UNVERIFIABLE",
      "headline": str,
      "narrative": str,
      "metrics": {...},                 # the OOS numbers, echoed back
      "findings": [                     # ranked what-to-fix, worst-first
        {"id", "cluster", "severity", "title", "detail", "suggestion"}
      ],
      "next_action": {"action", "label", "target", "strategy_name"},
    }

`cluster`  reuses referee.verdict.classify_failure vocabulary where it maps.
`severity` ∈ {"good","warn","bad","info"}  (drives colour + sort order).
"""
from __future__ import annotations

from typing import Any

SCHEMA = "studio.validation/1"

# ---- presentation thresholds (NOT validation math) --------------------------
# These only choose WORDS for numbers the engine already computed; they change
# no statistical test or pass/fail boundary. OVERFIT_DROP_WARN matches the value
# the walk-forward UI already flags overfit at (studio.walkforward.tsx), so the
# narrative and the existing colour cue agree.
OVERFIT_DROP_WARN = 0.5      # train Sharpe exceeding test by this = overfit cue
WINDOW_ROBUST_PCT = 60.0     # >= this share of windows positive = regime-robust
MIN_WINDOWS_CONFIDENT = 3    # fewer windows than this can't support confidence

# The referee call words, re-exported so callers/tests share one source.
VERDICTS = ("DEPLOY", "HOLD_CONDITIONAL", "REJECT", "UNVERIFIABLE")


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _sev_rank(sev: str) -> int:
    return {"bad": 0, "warn": 1, "good": 2, "info": 3}.get(sev, 4)


def _finding(fid, cluster, severity, title, detail, suggestion) -> dict[str, Any]:
    return {
        "id": fid,
        "cluster": cluster,
        "severity": severity,
        "title": title,
        "detail": detail,
        "suggestion": suggestion,
    }


def _next_action(verdict: str, strategy_name: str | None) -> dict[str, Any]:
    """The path back — never a dead string. Failing/conditional verdicts route
    the user toward editing & re-validating; a clean pass routes to deploy."""
    if verdict == "DEPLOY":
        return {
            "action": "deploy",
            "label": "Deploy to paper trading",
            "target": "studio.live",
            "strategy_name": strategy_name,
        }
    return {
        "action": "edit_strategy",
        "label": "Edit the strategy and re-validate",
        "target": "studio.strategies",
        "strategy_name": strategy_name,
    }


def analyze_walkforward(row: dict[str, Any]) -> dict[str, Any] | None:
    """Build a verdict from a walk-forward result row's existing metrics.

    Returns None while the run isn't finished or produced no out-of-sample
    measurement yet (the UI shows status/progress in that case). Otherwise
    returns the verdict structure above. Pure presentation — no metric here is
    recomputed; they are read from `row` and described.
    """
    status = str(row.get("status") or "").lower()
    strategy_name = row.get("strategy_name")

    s_test = _f(row.get("avg_test_sharpe"))
    s_train = _f(row.get("avg_train_sharpe"))
    overfit = _f(row.get("overfit_drop"))            # s_train - s_test
    r_test = _f(row.get("avg_test_return_pct"))
    win_windows = _f(row.get("win_rate_windows_pct"))
    n_windows = int(_f(row.get("num_windows")) or 0)

    # Not finished yet → no verdict to render (the page still shows progress).
    if status not in ("completed", "succeeded", "done"):
        return None

    metrics = {
        "avg_test_sharpe": s_test,
        "avg_train_sharpe": s_train,
        "overfit_drop": overfit,
        "avg_test_return_pct": r_test,
        "win_rate_windows_pct": win_windows,
        "num_windows": n_windows,
        "total_combos": row.get("total_combos"),
    }

    # Completed but no out-of-sample measurement → cannot grade (referee's
    # UNVERIFIABLE: the data couldn't be trusted, so no call is issued).
    if s_test is None or r_test is None or n_windows == 0:
        return {
            "schema": SCHEMA,
            "verdict": "UNVERIFIABLE",
            "headline": "Couldn't measure out-of-sample performance.",
            "narrative": (
                "The walk-forward finished but produced no usable out-of-sample "
                "result — typically too few bars for the train/test windows, or "
                "no trades in the test segments. No verdict can be issued."
            ),
            "metrics": metrics,
            "findings": [
                _finding(
                    "no-oos", "no_signal", "warn",
                    "No out-of-sample result",
                    "There weren't enough test-window trades/bars to compute an "
                    "out-of-sample Sharpe and return.",
                    "Extend the data range, lower train/test bar counts, or widen "
                    "entry/exit thresholds so the test windows actually trade.",
                )
            ],
            "next_action": _next_action("UNVERIFIABLE", strategy_name),
        }

    findings: list[dict[str, Any]] = []

    # ---- what failed / what held (ranked) — referee cluster vocabulary -------
    if s_test <= 0:
        findings.append(_finding(
            "oos-no-edge", "no_signal", "bad",
            f"No out-of-sample edge (test Sharpe {s_test:.2f})",
            "Averaged across the test windows the strategy is not positive on a "
            "risk-adjusted basis — the in-sample edge did not survive out of "
            "sample.",
            "Edit the entry/exit logic or target a different regime; tuning "
            "parameters on the same idea won't recover a missing edge.",
        ))
    elif r_test is not None and r_test <= 0:
        # Risk-adjusted positive but net return negative = the cost-wall cluster.
        findings.append(_finding(
            "oos-cost-wall", "gross_pos_net_neg", "bad",
            f"Costs eat the edge (test return {r_test:.2f}%)",
            "There is a faint risk-adjusted signal, but average out-of-sample "
            "net return is not positive — fees/slippage/whipsaw consume it.",
            "Raise the timeframe or cut churn so the per-trade edge clears the "
            "round-trip cost.",
        ))

    if overfit is not None and overfit > OVERFIT_DROP_WARN:
        findings.append(_finding(
            "overfit", "deflation_collapse",
            "bad" if overfit > 2 * OVERFIT_DROP_WARN else "warn",
            f"Overfit to the training windows (drop {overfit:.2f})",
            f"Train Sharpe {('%.2f' % s_train) if s_train is not None else '—'} "
            f"vs test {s_test:.2f}: the edge shrinks sharply out of sample, the "
            "signature of parameters tuned to the training window.",
            "Shrink the parameter grid and simplify the strategy so it isn't fit "
            "to one window; prefer fewer, more robust parameters.",
        ))

    if win_windows is not None and win_windows < WINDOW_ROBUST_PCT:
        findings.append(_finding(
            "single-regime", "single_regime", "warn",
            f"Edge holds in only {win_windows:.0f}% of windows",
            "The strategy is profitable out-of-sample in fewer than "
            f"{WINDOW_ROBUST_PCT:.0f}% of windows — it works in some periods and "
            "fails in others rather than across regimes.",
            "Add a regime filter (trend/volatility) or test more data; a "
            "window-dependent edge is a regime, not a robust strategy.",
        ))

    if 0 < n_windows < MIN_WINDOWS_CONFIDENT:
        findings.append(_finding(
            "low-windows", "low_sample", "warn",
            f"Only {n_windows} window(s)",
            f"{n_windows} walk-forward window(s) is too few to trust the "
            "out-of-sample average — one window swings it.",
            "Increase num_windows or extend the data so at least "
            f"{MIN_WINDOWS_CONFIDENT} test windows are evaluated.",
        ))

    # ---- verdict (referee call words) from the existing metrics --------------
    fails_oos = (s_test <= 0) or (r_test is not None and r_test <= 0)
    is_overfit = overfit is not None and overfit > OVERFIT_DROP_WARN
    not_robust = (win_windows is not None and win_windows < WINDOW_ROBUST_PCT)
    too_few = 0 < n_windows < MIN_WINDOWS_CONFIDENT

    if fails_oos:
        verdict = "REJECT"
    elif is_overfit or not_robust or too_few:
        verdict = "HOLD_CONDITIONAL"
    else:
        verdict = "DEPLOY"

    if verdict == "DEPLOY":
        findings.append(_finding(
            "oos-survivor", "survivor", "good",
            "Edge survived out-of-sample",
            f"Average test Sharpe {s_test:.2f} with a small overfit drop"
            + (f" ({overfit:.2f})" if overfit is not None else "")
            + (f" and {win_windows:.0f}% of windows positive"
               if win_windows is not None else "")
            + " — the edge holds where it counts.",
            "Validate live on paper before risking capital; size within your "
            "risk limits.",
        ))

    findings.sort(key=lambda f: _sev_rank(f["severity"]))

    # ---- headline + narrative (referee tone) --------------------------------
    if verdict == "REJECT":
        headline = "Fails out-of-sample — don't deploy as-is."
        bits = []
        if s_test <= 0:
            bits.append(f"test Sharpe {s_test:.2f} (not positive)")
        if r_test is not None and r_test <= 0:
            bits.append(f"test return {r_test:.2f}% (net-negative)")
        narrative = (
            "The strategy looked fine in training but did not hold up out of "
            "sample: " + "; ".join(bits) + ". The fixes below are ordered by "
            "impact — start at the top, then re-validate."
        )
    elif verdict == "HOLD_CONDITIONAL":
        headline = "Holds out-of-sample, but with caveats — a human call."
        why = []
        if is_overfit:
            why.append("it overfits the training windows")
        if not_robust:
            why.append(f"it only works in {win_windows:.0f}% of windows")
        if too_few:
            why.append(f"only {n_windows} window(s) were tested")
        narrative = (
            f"Out-of-sample is positive (test Sharpe {s_test:.2f}, return "
            f"{r_test:.2f}%), but " + "; and ".join(why) + ". Address the items "
            "below before trusting it, then re-validate — never auto-deploy a "
            "conditional pass."
        )
    else:  # DEPLOY
        headline = "Edge holds out-of-sample."
        narrative = (
            f"Positive out-of-sample (test Sharpe {s_test:.2f}, return "
            f"{r_test:.2f}%), a small train-to-test drop"
            + (f" ({overfit:.2f})" if overfit is not None else "")
            + (f", and {win_windows:.0f}% of windows profitable"
               if win_windows is not None else "")
            + ". This is the honest pass — validate on paper next."
        )

    return {
        "schema": SCHEMA,
        "verdict": verdict,
        "headline": headline,
        "narrative": narrative,
        "metrics": metrics,
        "findings": findings,
        "next_action": _next_action(verdict, strategy_name),
    }
