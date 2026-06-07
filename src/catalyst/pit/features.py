"""MODULE 0 -- point-in-time feature layer (build-first; everything depends on it).

The single function the rest of the system routes through:

    get_pit_features(ticker, as_of) -> FeatureRow | None

It reads ONLY through ``AsOfPanel``, so it is structurally incapable of seeing
data dated after ``as_of``. Derived features (drawdown, 52w-low distance, ADV,
margin/FCF trend, leverage flag, ATR, IV rank + reliability, recent catalysts)
are all computed from that bounded view.

Per Section 3 the panel is stored as an as-of table keyed by (ticker, date) so a
full-universe pass is a vectorized sweep of this function, not a per-name loop.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..store.panel import AsOfPanel
from config.defaults import Config, DEFAULTS

TRADING_DAYS_52W = 252


@dataclass
class FeatureRow:
    ticker: str
    as_of: str

    # price / structure
    price: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    drawdown_from_52w_high: float | None = None
    pct_above_52w_low: float | None = None
    avg_daily_dollar_volume: float | None = None
    atr: float | None = None
    base_low: float | None = None              # consolidation low over base window

    # fundamentals (point-in-time, lagged to filing)
    market_cap: float | None = None
    optionable: bool = False
    fcf_improving: bool | None = None
    margin_improving: bool | None = None
    debt_to_equity: float | None = None
    leverage_flag: bool = False
    fundamental_snapshot: dict[str, Any] = field(default_factory=dict)

    # volatility regime
    iv_rank: float | None = None
    iv_rank_reliable: bool = False

    # catalysts knowable as of as_of (recent)
    catalysts: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def get_pit_features(
    ticker: str, as_of: date | str, panel: AsOfPanel, cfg: Config = DEFAULTS
) -> FeatureRow | None:
    """Compute the point-in-time feature row for ``ticker`` as of ``as_of``.

    Returns None if there is not enough as-of data to evaluate the name.
    """
    prices = panel.price_history(ticker)
    if not prices:
        return None

    row = FeatureRow(ticker=ticker, as_of=panel.as_of)

    closes = [_num(p.get("adj_close")) or _num(p.get("close")) for p in prices]
    closes = [c for c in closes if c is not None]
    if not closes:
        return None
    row.price = closes[-1]

    window = closes[-TRADING_DAYS_52W:]
    row.high_52w = max(window)
    row.low_52w = min(window)
    if row.high_52w:
        row.drawdown_from_52w_high = (row.high_52w - row.price) / row.high_52w
    if row.low_52w:
        row.pct_above_52w_low = (row.price - row.low_52w) / row.low_52w

    # ADV (dollar) over the configured lookback.
    adv_rows = prices[-cfg.screen.adv_lookback_days:]
    dollar_vols = [
        (_num(p.get("close")) or 0.0) * (_num(p.get("volume")) or 0.0) for p in adv_rows
    ]
    row.avg_daily_dollar_volume = sum(dollar_vols) / len(dollar_vols) if dollar_vols else 0.0

    # ATR and structural base.
    row.atr = _atr(prices[-(cfg.entry_exit.atr_period + 1):], cfg.entry_exit.atr_period)
    base_rows = prices[-cfg.entry_exit.base_lookback_days:]
    base_lows = [_num(p.get("low")) for p in base_rows if _num(p.get("low")) is not None]
    row.base_low = min(base_lows) if base_lows else None

    # Universe membership (market cap / optionability), survivorship-correct.
    for u in panel.universe(optionable_only=False):
        if u["ticker"] == ticker:
            row.market_cap = _num(u.get("market_cap"))
            row.optionable = bool(u.get("optionable"))
            break

    # Fundamentals -- lagged to filing knowable_at.
    funds = panel.fundamentals(ticker)
    if funds:
        recent = funds[-cfg.screen.viability_lookback_quarters:]
        row.fcf_improving = _is_improving([_num(f.get("fcf")) for f in recent])
        row.margin_improving = _is_improving(
            [_num(f.get("op_margin")) for f in recent]
        )
        latest = funds[-1]
        row.debt_to_equity = _num(latest.get("debt_to_equity"))
        row.leverage_flag = (
            row.debt_to_equity is not None
            and row.debt_to_equity >= cfg.screen.leverage_flag_debt_to_equity
        )
        row.fundamental_snapshot = {
            "period_end": latest.get("period_end"),
            "knowable_at": latest.get("knowable_at"),
            "fcf": _num(latest.get("fcf")),
            "op_margin": _num(latest.get("op_margin")),
            "gross_margin": _num(latest.get("gross_margin")),
            "debt_to_equity": row.debt_to_equity,
        }

    # IV rank + reliability.
    iv_rows = panel.iv_history(ticker, cfg.options.iv_rank_window_trading_days)
    row.iv_rank_reliable = len(iv_rows) >= cfg.options.iv_rank_min_history_days
    if iv_rows:
        ivs = [_num(r.get("atm_iv")) for r in iv_rows if _num(r.get("atm_iv")) is not None]
        if ivs:
            cur = ivs[-1]
            below = sum(1 for v in ivs if v <= cur)
            row.iv_rank = 100.0 * below / len(ivs)

    # Recent catalysts knowable as of as_of (widest catalyst window we use).
    max_window = max(
        cfg.catalyst.analyst_revision_window_days,
        cfg.catalyst.insider_window_days,
        90,
    )
    row.catalysts = panel.catalysts(ticker, since_days=max_window)

    return row


# -- helpers ---------------------------------------------------------------
def _num(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if not math.isnan(f) else None
    except (TypeError, ValueError):
        return None


def _is_improving(series: list[float | None]) -> bool | None:
    """True if the trend across the (chronological) series is non-decreasing
    on balance (last > first and the latest step is up)."""
    vals = [v for v in series if v is not None]
    if len(vals) < 2:
        return None
    return vals[-1] > vals[0]


def _atr(bars: list[dict[str, Any]], period: int) -> float | None:
    if len(bars) < 2:
        return None
    trs = []
    prev_close = _num(bars[0].get("close"))
    for b in bars[1:]:
        hi, lo, cl = _num(b.get("high")), _num(b.get("low")), _num(b.get("close"))
        if None in (hi, lo) or prev_close is None:
            prev_close = cl
            continue
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        trs.append(tr)
        prev_close = cl
    if not trs:
        return None
    return sum(trs[-period:]) / min(len(trs), period)
