"""Deploy the winning crypto strategy as a first-class user strategy and verify
it with the real engine over the full 2025 window plus H1/H2 splits.

Winner (from the sweep chain): RSI(14) mean-reversion + SMA200 regime filter,
asymmetric exit (long->RSI55, short->RSI45) + 1.25% take-profit. On BTC-USDT 1h
2025: +12.3%, profit factor 1.38, win 69%, maxDD -17%, Sharpe 0.61, ~2.65 trd/wk.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import redis.asyncio as redis
from sqlalchemy import text

from packages.backtest.persistence import create_backtest
from packages.data.db import get_sessionmaker
from packages.data.messagebus import QUEUE_BACKTEST_JOBS
from packages.data.user_strategies import create_user_strategy, get_user_strategy_by_name
from packages.strategy.validator import validate_strategy_source

USER_EMAIL = "aliasfar2006@gmail.com"
SYMBOL = "BTC-USDT@BINANCEUS"
STRAT_NAME = "BTC Regime Reversion 1h"

SOURCE = '''"""BTC Regime Reversion (1h).

Long/short mean-reversion gated by a long-term trend (regime) filter.

Edge: on choppy crypto, RSI mean-reversion only pays when you take dips WITH the
larger trend and short rallies AGAINST a downtrend. The SMA regime filter does
exactly that; a naive (unfiltered) version is a coin-flip after fees. A small
take-profit banks the quick reversion bounce, and asymmetric exits let the move
run just past the mean before flattening.

Rules (single symbol):
  - regime = close vs SMA(sma_period)
  - LONG  when RSI(rsi_period) < entry_long  AND close > regime SMA
  - SHORT when RSI(rsi_period) > entry_short AND close < regime SMA
  - exit long  when RSI > exit_long  OR  +take_profit_pct reached
  - exit short when RSI < exit_short OR  +take_profit_pct reached (price falls)
  - sizes each entry at position_pct of available cash
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class RegimeReversionParams(BaseModel):
    """Parameters for the regime-filtered mean-reversion strategy."""

    model_config = {"extra": "forbid"}

    rsi_period: int = Field(default=14, ge=2, le=100,
                            description="RSI lookback in bars.")
    sma_period: int = Field(default=200, ge=20, le=400,
                            description="Regime filter: SMA lookback in bars.")
    entry_long: float = Field(default=43.0, ge=1, le=50,
                              description="Go long when RSI dips below this (and above the SMA).")
    entry_short: float = Field(default=57.0, ge=50, le=99,
                               description="Go short when RSI rises above this (and below the SMA).")
    exit_long: float = Field(default=55.0, ge=50, le=99,
                             description="Exit a long when RSI recovers above this.")
    exit_short: float = Field(default=45.0, ge=1, le=50,
                              description="Exit a short when RSI falls below this.")
    take_profit_pct: float = Field(default=0.0125, ge=0, le=0.2,
                                   description="Bank profit at this fraction from entry (0 disables).")
    position_pct: float = Field(default=90.0, gt=0, le=100,
                                description="Percent of available cash deployed per entry.")

    @model_validator(mode="after")
    def _check(self) -> "RegimeReversionParams":
        if self.entry_long >= self.entry_short:
            raise ValueError("entry_long must be below entry_short")
        return self


class RegimeReversion(Strategy[RegimeReversionParams]):
    """Regime-filtered RSI mean reversion, long/short, single symbol."""

    PARAMS_MODEL = RegimeReversionParams

    def on_init(self) -> None:
        if len(self.symbols) != 1:
            raise ValueError("RegimeReversion supports exactly one symbol")
        self.symbol = self.symbols[0]
        self.state["entry_px"] = None

    def on_bar(self, ctx: BarContext) -> None:
        sym = self.symbol
        p = self.params
        price = ctx.close(sym)
        rsi = ctx.rsi(sym, p.rsi_period)
        sma = ctx.sma(sym, p.sma_period)
        if price is None or rsi is None or sma is None or float(price) <= 0:
            return
        r = float(rsi)
        px = float(price)
        sv = float(sma)
        pos = ctx.position(sym)
        tp = p.take_profit_pct

        if pos == 0:
            qty = (p.position_pct / 100.0) * ctx.cash / price
            if qty <= 0:
                return
            if r < p.entry_long and px > sv:
                ctx.signal("regime_long", value=r, symbol=sym)
                ctx.submit_buy_market(sym, qty)
                self.state["entry_px"] = px
            elif r > p.entry_short and px < sv:
                ctx.signal("regime_short", value=r, symbol=sym)
                ctx.submit_sell_market(sym, qty)
                self.state["entry_px"] = px
        elif pos > 0:
            ep = self.state["entry_px"]
            tp_hit = tp > 0 and ep is not None and px >= ep * (1 + tp)
            if r > p.exit_long or tp_hit:
                ctx.signal("regime_long_exit", value=r, symbol=sym)
                ctx.submit_sell_market(sym, pos)
                self.state["entry_px"] = None
        else:
            ep = self.state["entry_px"]
            tp_hit = tp > 0 and ep is not None and px <= ep * (1 - tp)
            if r < p.exit_short or tp_hit:
                ctx.signal("regime_short_exit", value=r, symbol=sym)
                ctx.submit_buy_market(sym, -pos)
                self.state["entry_px"] = None
'''

WINDOWS = [
    ("full2025", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ("H1", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)),
    ("H2", datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
]


async def main():
    v = validate_strategy_source(SOURCE)
    if not v.ok:
        print("VALIDATION FAILED:", [e.as_dict() for e in v.errors])
        return
    print("validation ok, class:", v.class_name)

    sm = get_sessionmaker()
    async with sm() as s:
        u = (await s.execute(text("SELECT id, org_id FROM users WHERE email=:e"),
                             {"e": USER_EMAIL})).mappings().first()
        uid, oid = u["id"], u["org_id"]

    r = redis.from_url("redis://redis:6379/0")
    async with sm() as s:
        existing = await get_user_strategy_by_name(s, user_id=uid, name=STRAT_NAME)
        if existing is None:
            sid = await create_user_strategy(
                s, user_id=uid, org_id=oid, name=STRAT_NAME,
                description="Regime-filtered RSI mean reversion (long/short) on BTC 1h.",
                nl_description="Buy dips above the 200-SMA and short rallies below it, "
                                "using RSI(14); bank a 1.25% bounce or exit when RSI reverts.",
                class_name=v.class_name, source_code=SOURCE,
                params_schema=v.params_schema, asset_class="crypto")
            await s.commit()
            print("created strategy id:", sid)
        else:
            print("strategy already exists id:", existing["id"] if isinstance(existing, dict) else existing)

    jobs = []
    for tag, ws, we in WINDOWS:
        async with sm() as s:
            bt_id = await create_backtest(
                s, user_id=uid, org_id=oid, strategy_name=STRAT_NAME, params_json={},
                symbols=[SYMBOL], bar_resolution="1h", starting_cash=Decimal("25000"),
                fee_rate_bps=5, slippage_bps=3, window_start=ws, window_end=we)
            await s.commit()
        await r.lpush(QUEUE_BACKTEST_JOBS, str(bt_id))
        jobs.append((tag, str(bt_id)))
    print("queued verification backtests:", jobs)

    pending = {bt for _, bt in jobs}
    for _ in range(120):
        await asyncio.sleep(4)
        async with sm() as s:
            rows = (await s.execute(text(
                "SELECT id::text id, status FROM backtests WHERE id = ANY(:ids)"),
                {"ids": list(pending)})).mappings().all()
        pending -= {row["id"] for row in rows if row["status"] in ("completed", "failed")}
        if not pending:
            break
    print("unfinished:", len(pending))

    W = {"full2025": 365 / 7.0, "H1": 181 / 7.0, "H2": 184 / 7.0}
    async with sm() as s:
        for tag, bt in jobs:
            m = (await s.execute(text(
                "SELECT status, num_closed_trades n, "
                "(analysis_json->'metrics'->>'total_return_pct') ret, "
                "(analysis_json->'metrics'->>'profit_factor') pf, "
                "(analysis_json->'metrics'->>'win_rate_pct') wr, "
                "(analysis_json->'metrics'->>'max_drawdown_pct') dd, "
                "(analysis_json->'metrics'->>'sharpe') sh "
                "FROM backtests WHERE id=:b"), {"b": bt})).mappings().first()
            n = m["n"] or 0
            tpw = n / W[tag]
            ret = f"{float(m['ret']):.1f}%" if m["ret"] else "n/a"
            pf = f"{float(m['pf']):.2f}" if m["pf"] else "n/a"
            wr = f"{float(m['wr']):.0f}" if m["wr"] else "n/a"
            dd = f"{float(m['dd']):.0f}" if m["dd"] else "n/a"
            sh = f"{float(m['sh']):.2f}" if m["sh"] else "n/a"
            print(f"{tag:9} {m['status']:9} trades={n:4d} tpw={tpw:5.2f} ret={ret:>7} "
                  f"pf={pf:>5} win={wr:>3} dd={dd:>4} sharpe={sh:>5}  bt={bt}")


if __name__ == "__main__":
    asyncio.run(main())
