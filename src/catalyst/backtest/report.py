"""MODULE 6 -- backtest report generator.

Segments by catalyst_type AND by regime (mandatory, Section 9): never blends
distinct catalyst distributions or eras into one statistic. REFUSES to report
stats for any bucket under the minimum N (Section 11 kill condition).

Reports the GAP between fixed-horizon return (does the signal predict?) and
rules-based realized return (does the system capture it?).

ANTI-BIAS RULE #6: there is NO branch, weight, or threshold anywhere in this
module keyed on the four archetype names (held in config, never referenced here).
Recapturing the archetypes is a sanity check a human may eyeball, never a computed
validation metric. The decision path is scanned for those literals by
tests/test_archetype_not_scored.py and scripts/verify.py -- any appearance fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .engine import Trade
from .stats import compute, Stats
from config.defaults import Config, DEFAULTS


@dataclass
class BucketReport:
    label: str
    n_signals: int
    n_filled: int
    no_fill_rate: float
    reported: bool                      # False => below min N, stats suppressed
    suppressed_reason: str = ""
    fixed_horizon_stats: dict[int, Stats] = field(default_factory=dict)
    rules_stats: Stats | None = None
    capture_gap: dict[int, float | None] = field(default_factory=dict)


def _regime_of(signal_date: str, boundaries: tuple[str, ...]) -> str:
    for i, b in enumerate(boundaries):
        if signal_date < b:
            prev = boundaries[i - 1] if i > 0 else "start"
            return f"{prev}..{b}"
    last = boundaries[-1] if boundaries else "start"
    return f"{last}..present"


def _bucket(trades: list[Trade], label: str, cfg: Config) -> BucketReport:
    n_signals = len(trades)
    filled = [t for t in trades if t.filled]
    n_filled = len(filled)
    no_fill_rate = 1 - (n_filled / n_signals) if n_signals else 0.0

    min_n = cfg.backtest.min_trades_per_bucket
    if n_filled < min_n:
        return BucketReport(
            label=label, n_signals=n_signals, n_filled=n_filled,
            no_fill_rate=no_fill_rate, reported=False,
            suppressed_reason=f"n_filled={n_filled} < min_trades_per_bucket={min_n}",
        )

    rep = BucketReport(label=label, n_signals=n_signals, n_filled=n_filled,
                       no_fill_rate=no_fill_rate, reported=True)

    # Fixed-horizon stats per horizon.
    for m in cfg.backtest.forward_horizons_months:
        rets = [t.fixed_horizon.get(m) for t in filled]
        rets = [r for r in rets if r is not None]
        if rets:
            rep.fixed_horizon_stats[m] = compute(
                rets, bootstrap_iters=cfg.backtest.bootstrap_iterations,
                ci=cfg.backtest.bootstrap_ci,
            )

    # Rules-based realized stats.
    rules_rets = [t.rules_return for t in filled if t.rules_return is not None]
    rep.rules_stats = compute(rules_rets, bootstrap_iters=cfg.backtest.bootstrap_iterations,
                              ci=cfg.backtest.bootstrap_ci) if rules_rets else None

    # Capture gap = fixed-horizon expectancy - rules expectancy, per horizon.
    if rep.rules_stats and rep.rules_stats.expectancy is not None:
        for m, st in rep.fixed_horizon_stats.items():
            if st.expectancy is not None:
                rep.capture_gap[m] = st.expectancy - rep.rules_stats.expectancy
    return rep


def generate(trades: list[Trade], cfg: Config = DEFAULTS) -> dict[str, Any]:
    """Build the full segmented report. Keys: by_catalyst, by_regime, by_cell."""
    by_catalyst: dict[str, BucketReport] = {}
    cat_types = sorted({t.catalyst_type for t in trades})
    for ct in cat_types:
        by_catalyst[ct] = _bucket([t for t in trades if t.catalyst_type == ct], ct, cfg)

    by_regime: dict[str, BucketReport] = {}
    regimes = sorted({_regime_of(t.signal_date, cfg.backtest.regime_boundaries) for t in trades})
    for rg in regimes:
        sel = [t for t in trades if _regime_of(t.signal_date, cfg.backtest.regime_boundaries) == rg]
        by_regime[rg] = _bucket(sel, rg, cfg)

    # Cross-cell: catalyst x regime (the strongest anti-overfit lens).
    by_cell: dict[str, BucketReport] = {}
    for ct in cat_types:
        for rg in regimes:
            sel = [t for t in trades
                   if t.catalyst_type == ct
                   and _regime_of(t.signal_date, cfg.backtest.regime_boundaries) == rg]
            if sel:
                by_cell[f"{ct} @ {rg}"] = _bucket(sel, f"{ct} @ {rg}", cfg)

    return {
        "total_signals": len(trades),
        "total_filled": sum(1 for t in trades if t.filled),
        "min_trades_per_bucket": cfg.backtest.min_trades_per_bucket,
        "by_catalyst": by_catalyst,
        "by_regime": by_regime,
        "by_cell": by_cell,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = ["=" * 70, "CATALYST BREAKOUT -- BACKTEST REPORT", "=" * 70,
             f"Total fired signals: {report['total_signals']}  "
             f"filled: {report['total_filled']}  "
             f"(min N/bucket = {report['min_trades_per_bucket']})", ""]
    for section in ("by_catalyst", "by_regime", "by_cell"):
        lines.append(f"--- {section.upper()} ---")
        for label, b in report[section].items():
            lines.append(_render_bucket(b))
        lines.append("")
    return "\n".join(lines)


def _render_bucket(b: BucketReport) -> str:
    head = (f"  [{b.label}]  signals={b.n_signals} filled={b.n_filled} "
            f"no_fill={b.no_fill_rate:.0%}")
    if not b.reported:
        return head + f"\n      SUPPRESSED: {b.suppressed_reason}"
    out = [head]
    if b.rules_stats:
        s = b.rules_stats
        ci = f"[{s.expectancy_ci[0]:+.3f},{s.expectancy_ci[1]:+.3f}]" if s.expectancy_ci else "n/a"
        out.append(
            f"      rules: exp={s.expectancy:+.3f} ci95={ci} win={s.win_rate:.0%} "
            f"pf={_f(s.profit_factor)} payoff={_f(s.payoff_ratio)} "
            f"mdd={_f(s.max_drawdown)} sortino={_f(s.sortino)}"
        )
    for m, st in sorted(b.fixed_horizon_stats.items()):
        gap = b.capture_gap.get(m)
        gap_s = f" gap={gap:+.3f}" if gap is not None else ""
        out.append(f"      fwd{m}m: exp={st.expectancy:+.3f} win={st.win_rate:.0%}{gap_s}")
    return "\n".join(out)


def _f(v) -> str:
    return f"{v:.2f}" if v is not None else "n/a"
