"""MODULE 1 -- distressed-and-viable wide screen.

Stage-one filter over the optionable universe. Produces a slow-moving watchlist
(typically 150-400 names per Section 4). This set is NOT a signal -- it is the
pool the catalyst gate (Module 2) draws from.

All thresholds come from cfg.screen; nothing is hardcoded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..pit.features import FeatureRow
from config.defaults import Config, DEFAULTS


@dataclass
class ScreenResult:
    ticker: str
    passed: bool
    reasons: dict[str, bool]
    leverage_flag: bool
    distress_metrics: dict[str, Any]


def passes_screen(row: FeatureRow, cfg: Config = DEFAULTS) -> ScreenResult:
    s = cfg.screen
    reasons: dict[str, bool] = {}

    # Market cap floor.
    reasons["market_cap"] = (
        row.market_cap is not None and row.market_cap >= s.market_cap_floor_usd
    )

    # Distressed: big drawdown OR near 52w low. When require_distress is False
    # the gate is disabled (passes regardless) -- this removes the core thesis;
    # see ScreenConfig.require_distress.
    distressed_drawdown = (
        row.drawdown_from_52w_high is not None
        and row.drawdown_from_52w_high >= s.min_drawdown_from_52w_high
    )
    near_low = (
        row.pct_above_52w_low is not None
        and row.pct_above_52w_low <= s.within_pct_of_52w_low
    )
    reasons["distressed"] = (not s.require_distress) or distressed_drawdown or near_low

    # Viability: improving FCF OR improving margin trend.
    reasons["viable"] = bool(row.fcf_improving) or bool(row.margin_improving)

    # Liquidity.
    reasons["liquidity"] = (
        row.avg_daily_dollar_volume is not None
        and row.avg_daily_dollar_volume >= s.min_avg_daily_dollar_volume_usd
    )

    # Optionability.
    reasons["optionable"] = (not s.require_listed_options) or row.optionable

    passed = all(reasons.values())
    return ScreenResult(
        ticker=row.ticker,
        passed=passed,
        reasons=reasons,
        leverage_flag=row.leverage_flag,  # FLAGGED, not excluded.
        distress_metrics={
            "drawdown_from_52w_high": row.drawdown_from_52w_high,
            "pct_above_52w_low": row.pct_above_52w_low,
            "distressed_by_drawdown": distressed_drawdown,
            "near_52w_low": near_low,
        },
    )
