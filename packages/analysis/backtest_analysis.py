"""Deterministic backtest analysis.

`analyze_backtest` consumes the data a backtest already produces — performance
metrics, per-symbol / per-signal attribution, and the signal-edge ML model — and
emits a structured verdict + ranked list of findings, each with a concrete
suggestion. No LLM, no external calls: every statement is derived arithmetically
from the inputs, so it is fast, free, and testable.

Output shape (all JSON-serializable)::

    {
      "schema": 1,
      "verdict": "profitable" | "marginal" | "unprofitable" | "inconclusive",
      "headline": str,
      "score": int,                     # 0-100 overall quality
      "metrics": {...},                 # the key numbers used, echoed back
      "findings": [
        {"id", "kind", "severity", "title", "detail", "suggestion"}
      ],
      "narrative": null                 # filled by the optional LLM layer
    }

`kind`     ∈ {"verdict","signal","symbol","risk","sample","metric","data"}
`severity` ∈ {"good","warn","bad","info"}  (drives colour + sort order)
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1

# A backtest with fewer than this many closed trades can't support confident
# conclusions; we down-rank the verdict and say so.
MIN_TRADES_CONFIDENT = 30
# A signal/symbol needs at least this many tagged trades before we judge its
# win rate (otherwise it's noise).
MIN_TRADES_JUDGE = 8
# Profit concentration above this share in a single symbol is fragile.
CONCENTRATION_WARN = 0.6
# Signal predicted-edge (percentage points vs. base) thresholds.
EDGE_STRONG_PP = 8.0
EDGE_DRAG_PP = -8.0


def _f(v: Any) -> float | None:
    """Coerce a metric to float; None/'' stay None (so missing != 0)."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _money(v: Any) -> float:
    f = _f(v)
    return f if f is not None else 0.0


def _sev_rank(sev: str) -> int:
    return {"bad": 0, "warn": 1, "good": 2, "info": 3}.get(sev, 4)


def analyze_backtest(
    metrics: dict[str, Any],
    attribution: dict[str, Any] | None,
    ml_model: dict[str, Any] | None,
) -> dict[str, Any]:
    """Produce a structured, deterministic analysis of one backtest run."""
    findings: list[dict[str, Any]] = []

    sharpe = _f(metrics.get("sharpe_ratio"))
    sortino = _f(metrics.get("sortino_ratio"))
    pf = _f(metrics.get("profit_factor"))
    win = _f(metrics.get("win_rate_pct"))
    avg_win = _f(metrics.get("avg_winner_pct"))
    avg_loss = _f(metrics.get("avg_loser_pct"))  # negative or magnitude
    max_dd = _f(metrics.get("max_drawdown_pct"))  # <= 0
    total_ret = _f(metrics.get("total_return_pct"))
    n_trades = int(_f(metrics.get("num_closed_trades")) or 0)

    # ---- Expectancy / breakeven (the "why it works / doesn't") ----
    payoff = None
    breakeven_win = None
    expectancy_pct = None
    if avg_win is not None and avg_loss is not None and avg_loss != 0:
        loss_mag = abs(avg_loss)
        if loss_mag > 0:
            payoff = avg_win / loss_mag
            breakeven_win = 100.0 / (1.0 + payoff)  # win% needed to break even
            if win is not None:
                w = win / 100.0
                expectancy_pct = w * avg_win - (1 - w) * loss_mag

    # ============================================================
    # 1) Headline verdict from profit factor + sample
    # ============================================================
    if n_trades == 0:
        verdict = "inconclusive"
        findings.append(_finding(
            "no-trades", "sample", "warn", "No closed trades",
            "The strategy never opened and closed a position in this window.",
            "Loosen entry conditions, widen the date range, or confirm the "
            "instrument has bars over the test period.",
        ))
    elif pf is None:
        verdict = "profitable" if (total_ret or 0) > 0 else "inconclusive"
    elif pf >= 1.6:
        verdict = "profitable"
    elif pf >= 1.05:
        verdict = "marginal"
    else:
        verdict = "unprofitable"

    if pf is not None and n_trades > 0:
        if pf >= 1.6:
            findings.append(_finding(
                "pf-strong", "metric", "good", f"Profit factor {pf:.2f}",
                f"Gross wins are {pf:.2f}× gross losses — a robust edge over "
                f"{n_trades} trades.",
                "Healthy. Focus on scaling position size within your risk limits "
                "and confirming the edge holds out-of-sample.",
            ))
        elif pf >= 1.05:
            findings.append(_finding(
                "pf-marginal", "metric", "warn", f"Profit factor {pf:.2f}",
                f"Wins only modestly exceed losses ({pf:.2f}×). After "
                f"real-world slippage this edge may evaporate.",
                "Tighten exits or filter the lowest-quality entries to push "
                "profit factor above ~1.3 before trusting it.",
            ))
        else:
            findings.append(_finding(
                "pf-weak", "metric", "bad", f"Profit factor {pf:.2f}",
                f"Gross losses exceed gross wins ({pf:.2f}×) — the strategy "
                f"loses money before costs are even considered.",
                "Don't deploy. Invert or remove the worst signals (below) or "
                "rethink the entry logic.",
            ))

    # ============================================================
    # 2) Win rate vs. payoff (the core math of the edge)
    # ============================================================
    if breakeven_win is not None and win is not None:
        margin = win - breakeven_win
        if margin >= 5:
            findings.append(_finding(
                "winrate-ok", "metric", "good",
                f"Win rate {win:.0f}% clears breakeven {breakeven_win:.0f}%",
                f"With a {payoff:.2f}:1 payoff you need {breakeven_win:.0f}% wins "
                f"to break even and you're hitting {win:.0f}%. "
                f"Expectancy ≈ {expectancy_pct:+.2f}% per trade.",
                "The win-rate / payoff balance is sound.",
            ))
        elif margin >= -2:
            findings.append(_finding(
                "winrate-thin", "metric", "warn",
                f"Win rate {win:.0f}% barely meets breakeven {breakeven_win:.0f}%",
                f"At a {payoff:.2f}:1 payoff, breakeven is {breakeven_win:.0f}%. "
                f"You're at {win:.0f}% — almost no margin. "
                f"Expectancy ≈ {expectancy_pct:+.2f}% per trade.",
                "Either raise the win rate (better entry filter) or improve the "
                "payoff (let winners run / cut losers faster).",
            ))
        else:
            findings.append(_finding(
                "winrate-below", "metric", "bad",
                f"Win rate {win:.0f}% is below breakeven {breakeven_win:.0f}%",
                f"A {payoff:.2f}:1 payoff needs {breakeven_win:.0f}% wins; you only "
                f"win {win:.0f}%. Expectancy ≈ {expectancy_pct:+.2f}% per trade — "
                "negative.",
                "Raise the payoff ratio (wider targets / tighter stops) or add a "
                "filter that removes the losing cohort identified below.",
            ))

    # ============================================================
    # 3) Risk: drawdown + risk-adjusted return
    # ============================================================
    if sharpe is not None:
        if sharpe >= 1.0:
            findings.append(_finding(
                "sharpe-good", "risk", "good", f"Sharpe {sharpe:.2f}",
                "Risk-adjusted return is solid for a single backtest.",
                "Validate with walk-forward — in-sample Sharpe overstates live.",
            ))
        elif sharpe < 0:
            findings.append(_finding(
                "sharpe-neg", "risk", "bad", f"Sharpe {sharpe:.2f}",
                "Negative risk-adjusted return: the equity curve trended down "
                "relative to its volatility.",
                "The strategy is not viable as-is.",
            ))
        elif sharpe < 0.5:
            findings.append(_finding(
                "sharpe-low", "risk", "warn", f"Sharpe {sharpe:.2f}",
                "Low risk-adjusted return — returns are small relative to the "
                "volatility taken on.",
                "Reduce churn/whipsaw or size down; a low-Sharpe edge is fragile.",
            ))
    if max_dd is not None and max_dd <= -25:
        findings.append(_finding(
            "dd-deep", "risk", "warn", f"Max drawdown {max_dd:.0f}%",
            f"Peak-to-trough equity fell {abs(max_dd):.0f}%. Few people can hold "
            "through a drawdown that deep without abandoning the strategy.",
            "Add a regime filter or volatility-based position sizing to cap "
            "drawdown.",
        ))

    # ============================================================
    # 4) Sample size confidence
    # ============================================================
    if 0 < n_trades < MIN_TRADES_CONFIDENT:
        if verdict == "profitable":
            verdict = "marginal"
        findings.append(_finding(
            "low-sample", "sample", "warn", f"Only {n_trades} trades",
            f"{n_trades} closed trades is too few to trust any metric — one or "
            "two outcomes swing every ratio.",
            "Extend the date range or test across more symbols to reach "
            f"{MIN_TRADES_CONFIDENT}+ trades before drawing conclusions.",
        ))

    # ============================================================
    # 5) Per-signal attribution — which filters worked / hurt
    # ============================================================
    if attribution:
        findings.extend(_signal_findings(attribution))
        findings.extend(_symbol_findings(attribution))

    # ============================================================
    # 6) ML signal-edge model — predictive (not just realized) edge
    # ============================================================
    if ml_model:
        findings.extend(_ml_findings(ml_model))

    # ---- Sort: worst-first within (bad, warn, good, info) ----
    findings.sort(key=lambda f: _sev_rank(f["severity"]))

    score = _score(pf, sharpe, max_dd, n_trades, win, breakeven_win)
    headline = _headline(verdict, pf, sharpe, n_trades)

    return {
        "schema": SCHEMA_VERSION,
        "verdict": verdict,
        "headline": headline,
        "score": score,
        "metrics": {
            "profit_factor": pf,
            "sharpe": sharpe,
            "sortino": sortino,
            "win_rate_pct": win,
            "breakeven_win_pct": breakeven_win,
            "payoff_ratio": payoff,
            "expectancy_pct": expectancy_pct,
            "max_drawdown_pct": max_dd,
            "total_return_pct": total_ret,
            "num_closed_trades": n_trades,
        },
        "findings": findings,
        "narrative": None,
    }


# ============================================================
# Section builders
# ============================================================
def _signal_findings(attribution: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    signals = attribution.get("by_signal") or []
    for s in signals:
        name = s.get("name", "?")
        n = int(s.get("num_trades") or 0)
        wr = _f(s.get("win_rate_pct"))
        net = _money(s.get("net_pnl"))
        share = _f(s.get("pct_of_total_net_pnl"))
        block_rate = _f(s.get("block_rate_pct"))

        if n >= MIN_TRADES_JUDGE and net < 0:
            out.append(_finding(
                f"sig-drag-{name}", "signal", "bad",
                f"Signal “{name}” is a net drag",
                f"Trades it tagged lost ${abs(net):,.0f} over {n} trades"
                + (f" (win rate {wr:.0f}%)" if wr is not None else "")
                + ". This filter is actively hurting performance.",
                f"Try removing “{name}”, inverting its condition, or using it as "
                "a blocker instead of an entry trigger.",
            ))
        elif n >= MIN_TRADES_JUDGE and share is not None and share >= 25:
            out.append(_finding(
                f"sig-driver-{name}", "signal", "good",
                f"Signal “{name}” drives the edge",
                f"It accounts for {share:.0f}% of net P&L across {n} trades"
                + (f" at a {wr:.0f}% win rate" if wr is not None else "")
                + ".",
                f"Lean into “{name}” — consider weighting entries it tags more "
                "heavily, and make sure it isn't over-fit to this window.",
            ))
        if block_rate is not None and block_rate >= 98 and n < MIN_TRADES_JUDGE:
            out.append(_finding(
                f"sig-rare-{name}", "signal", "info",
                f"Signal “{name}” almost never fires",
                f"It blocked {block_rate:.0f}% of evaluations and tagged only {n} "
                "trades — it has negligible influence on results.",
                "Loosen its threshold if you intended it to matter, or drop it to "
                "simplify the strategy.",
            ))

    untagged = int(attribution.get("untagged_trades") or 0)
    total = int(attribution.get("num_closed_trades") or 0)
    if total > 0 and untagged / total >= 0.5 and signals:
        out.append(_finding(
            "untagged", "data", "info",
            f"{untagged}/{total} trades carry no signal tag",
            "Most P&L isn't attributable to any emitted signal, so the analysis "
            "can't explain why those trades fired.",
            "Instrument the strategy with ctx.signal(name, passed=, value=) on "
            "its key conditions to unlock per-signal attribution.",
        ))
    elif total > 0 and not signals:
        out.append(_finding(
            "no-signals", "data", "info",
            "Strategy emits no signals",
            "Without ctx.signal(...) calls there's no per-filter attribution — "
            "only symbol-level and aggregate metrics are available.",
            "Add ctx.signal(...) on each entry condition to see which filters "
            "actually drive (or drag) returns.",
        ))
    return out


def _symbol_findings(attribution: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    symbols = attribution.get("by_symbol") or []
    if not symbols:
        return out

    # Worst symbol (list is sorted desc by net P&L → last is worst).
    worst = symbols[-1]
    w_net = _money(worst.get("net_pnl"))
    w_share = _f(worst.get("pct_of_total_net_pnl"))
    w_n = int(worst.get("num_trades") or 0)
    if w_net < 0 and w_n >= MIN_TRADES_JUDGE:
        out.append(_finding(
            f"sym-worst-{worst.get('symbol')}", "symbol", "warn",
            f"{worst.get('symbol')} is your worst market",
            f"It lost ${abs(w_net):,.0f} over {w_n} trades"
            + (f" ({w_share:+.0f}% of net P&L)" if w_share is not None else "")
            + ".",
            f"Consider excluding {worst.get('symbol')} or tuning parameters per "
            "asset — one symbol can mask an otherwise-good strategy.",
        ))

    # Concentration risk: best symbol dominates the profit.
    best = symbols[0]
    b_share = _f(best.get("pct_of_total_net_pnl"))
    b_net = _money(best.get("net_pnl"))
    if b_net > 0 and b_share is not None and b_share / 100.0 >= CONCENTRATION_WARN:
        out.append(_finding(
            f"sym-concentrated-{best.get('symbol')}", "symbol", "warn",
            f"Profit concentrated in {best.get('symbol')}",
            f"{best.get('symbol')} alone is {b_share:.0f}% of net P&L. The edge "
            "may not generalize beyond this one market.",
            "Re-run across more symbols; if the edge only exists in one name, "
            "treat the result with caution.",
        ))
    return out


def _ml_findings(ml_model: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not ml_model.get("fitted"):
        reason = ml_model.get("reason")
        if reason:
            out.append(_finding(
                "ml-unfit", "metric", "info", "Signal-edge model not fitted",
                f"The ML edge model couldn't fit: {reason}. Empirical edges are "
                "still shown but predicted edges fall back to the base rate.",
                "Accumulate more trades (the cross-backtest store keeps learning "
                "as you run more backtests).",
            ))
        return out

    base = _f(ml_model.get("base_profit_rate"))
    for e in ml_model.get("signal_edges") or []:
        name = e.get("name", "?")
        lift = _f(e.get("lift_vs_base_pp"))
        n = int(e.get("num_trades") or 0)
        emp = _f(e.get("empirical_profit_rate"))
        if lift is None or n < MIN_TRADES_JUDGE:
            continue
        if lift >= EDGE_STRONG_PP:
            out.append(_finding(
                f"ml-edge-{name}", "signal", "good",
                f"Model: “{name}” predicts winners (+{lift:.0f}pp)",
                f"When “{name}” is active, modelled win probability is {lift:.0f} "
                f"points above the {base*100:.0f}% base rate"
                + (f"; empirically {emp*100:.0f}% profitable" if emp is not None else "")
                + f" over {n} trades.",
                f"“{name}” carries real predictive edge — gate or size entries on "
                "it.",
            ))
        elif lift <= EDGE_DRAG_PP:
            out.append(_finding(
                f"ml-drag-{name}", "signal", "bad",
                f"Model: “{name}” predicts losers ({lift:.0f}pp)",
                f"When “{name}” is active, modelled win probability is {abs(lift):.0f} "
                f"points BELOW the {base*100:.0f}% base rate over {n} trades.",
                f"Invert “{name}” or use it to block entries rather than trigger "
                "them.",
            ))
    return out


# ============================================================
# Scoring + headline
# ============================================================
def _score(pf, sharpe, max_dd, n_trades, win, breakeven) -> int:
    """Blend the key dimensions into a 0-100 quality score (deterministic)."""
    parts: list[float] = []
    # Profit factor → 0..40
    if pf is not None:
        parts.append(max(0.0, min(40.0, (pf - 0.8) / (2.0 - 0.8) * 40.0)))
    # Sharpe → 0..30
    if sharpe is not None:
        parts.append(max(0.0, min(30.0, (sharpe + 0.5) / (2.0 + 0.5) * 30.0)))
    # Drawdown → 0..15 (shallower is better)
    if max_dd is not None:
        parts.append(max(0.0, min(15.0, (1 - abs(max_dd) / 50.0) * 15.0)))
    # Win-rate margin over breakeven → 0..15
    if win is not None and breakeven is not None:
        parts.append(max(0.0, min(15.0, (win - breakeven + 10) / 30.0 * 15.0)))
    if not parts:
        return 0
    raw = sum(parts)
    # Penalize tiny samples (cap confidence).
    if 0 < n_trades < MIN_TRADES_CONFIDENT:
        raw *= 0.6 + 0.4 * (n_trades / MIN_TRADES_CONFIDENT)
    elif n_trades == 0:
        return 0
    return int(round(max(0, min(100, raw))))


def _headline(verdict, pf, sharpe, n_trades) -> str:
    if verdict == "inconclusive" or n_trades == 0:
        return "Not enough activity to judge this strategy."
    pf_s = f"profit factor {pf:.2f}" if pf is not None else "no losing trades"
    sh_s = f", Sharpe {sharpe:.2f}" if sharpe is not None else ""
    if verdict == "profitable":
        return f"Looks profitable — {pf_s}{sh_s} over {n_trades} trades, but validate out-of-sample."
    if verdict == "marginal":
        return f"Marginal edge — {pf_s}{sh_s}. Needs tightening before it's deployable."
    return f"Unprofitable as configured — {pf_s}{sh_s}. See the fixes below."


def _finding(fid, kind, severity, title, detail, suggestion) -> dict[str, Any]:
    return {
        "id": fid,
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "suggestion": suggestion,
    }
