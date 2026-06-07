"""MODULE 6 -- trade-level statistics + bootstrap CIs.

Expectancy, win rate, payoff ratio, profit factor, max drawdown, Sortino on
trade-level returns, plus bootstrap / Monte-Carlo confidence intervals on
expectancy (Section 9). The sample is small and clustered, so the CI matters as
much as the point estimate.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class Stats:
    n: int
    expectancy: float | None = None
    win_rate: float | None = None
    payoff_ratio: float | None = None
    profit_factor: float | None = None
    max_drawdown: float | None = None
    sortino: float | None = None
    expectancy_ci: tuple[float, float] | None = None


def compute(returns: Sequence[float], *, bootstrap_iters: int = 10_000,
            ci: float = 0.95, seed: int = 12345) -> Stats:
    rs = [float(r) for r in returns]
    n = len(rs)
    if n == 0:
        return Stats(n=0)

    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]

    expectancy = sum(rs) / n
    win_rate = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else None
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None

    return Stats(
        n=n,
        expectancy=expectancy,
        win_rate=win_rate,
        payoff_ratio=payoff_ratio,
        profit_factor=profit_factor,
        max_drawdown=_max_drawdown(rs),
        sortino=_sortino(rs),
        expectancy_ci=_bootstrap_ci(rs, bootstrap_iters, ci, seed),
    )


def _max_drawdown(returns: Sequence[float]) -> float:
    """Max drawdown of the cumulative (compounded) equity curve."""
    equity, peak, mdd = 1.0, 1.0, 0.0
    for r in returns:
        equity *= (1.0 + r)
        peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak)
    return mdd


def _sortino(returns: Sequence[float], target: float = 0.0) -> float | None:
    n = len(returns)
    if n < 2:
        return None
    mean = sum(returns) / n
    downside = [min(0.0, r - target) ** 2 for r in returns]
    dd = math.sqrt(sum(downside) / n)
    if dd == 0:
        return None
    return (mean - target) / dd


def _bootstrap_ci(returns: Sequence[float], iters: int, ci: float,
                  seed: int) -> tuple[float, float] | None:
    n = len(returns)
    if n < 2:
        return None
    rng = random.Random(seed)  # seeded => reproducible (no Math.random surprises)
    means = []
    for _ in range(iters):
        sample = [returns[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo_idx = int((1 - ci) / 2 * iters)
    hi_idx = int((1 + ci) / 2 * iters) - 1
    return (means[lo_idx], means[max(hi_idx, lo_idx)])
