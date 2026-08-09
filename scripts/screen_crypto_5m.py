"""Queue a 5m full-2-year regime-reversion screen across the 28-symbol crypto
universe.

Same long-only band as the 1h screen (RSI14, entry<42 above SMA / exit>60,
tp 4% / sl 6%, pos 90%) so the ONLY change is bar size -> isolates the
cost-wall / trade-frequency effect at 5m. Regime SMA is scaled to 2400 bars
(= 200h, matching the 1h winner's 200-bar/200h regime in wall-clock).

Queue-only: 28 backtests at ~259k bars each run ~20 min apiece on the single
serial worker (~9.5 hr total), so this script just enqueues and exits. Monitor
the `_screen5m_%` rows directly.
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
WIN_START = datetime(2024, 6, 15, tzinfo=timezone.utc)
WIN_END = datetime(2026, 6, 15, tzinfo=timezone.utc)

SYMBOLS = [
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "LTC",
    "XLM", "NEAR", "HBAR", "FET", "SUI", "ALGO", "BCH", "DOT", "SHIB", "ATOM",
    "ICP", "FIL", "UNI", "OP", "ARB", "ETC", "AAVE", "APT",
]

# Long-only band, identical to the 1h screen; SMA scaled to 5m (2400 = 200h).
RSI, SMA, LO, LE, TP, SL = 14, 2400, 42, 60, 0.04, 0.06


def build_source(name: str) -> str:
    return f'''"""SCREEN 5m {name}."""
from __future__ import annotations

from pydantic import BaseModel, Field

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class P(BaseModel):
    model_config = {{"extra": "forbid"}}

    rsi_period: int = Field(default={RSI}, ge=2, le=100)
    sma_period: int = Field(default={SMA}, ge=20, le=5000)
    entry_long: float = Field(default={LO}.0, ge=1, le=50)
    exit_long: float = Field(default={LE}.0, ge=50, le=99)
    take_profit_pct: float = Field(default={TP}, ge=0, le=0.5)
    stop_loss_pct: float = Field(default={SL}, ge=0, le=0.5)
    position_pct: float = Field(default=90.0, gt=0, le=100)


class S(Strategy[P]):
    PARAMS_MODEL = P

    def on_init(self) -> None:
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
        if pos == 0:
            qty = (p.position_pct / 100.0) * ctx.cash / price
            if qty <= 0:
                return
            if r < p.entry_long and px > sv:
                ctx.signal("regime_long", value=r, symbol=sym)
                ctx.submit_buy_market(sym, qty)
                self.state["entry_px"] = px
        elif pos > 0:
            ep = self.state["entry_px"]
            tp_hit = p.take_profit_pct > 0 and ep is not None and px >= ep * (1 + p.take_profit_pct)
            sl_hit = p.stop_loss_pct > 0 and ep is not None and px <= ep * (1 - p.stop_loss_pct)
            if r > p.exit_long or tp_hit or sl_hit:
                ctx.signal("regime_long_exit", value=r, symbol=sym)
                ctx.submit_sell_market(sym, pos)
                self.state["entry_px"] = None
'''


async def main():
    sm = get_sessionmaker()
    async with sm() as s:
        u = (await s.execute(text("SELECT id, org_id FROM users WHERE email=:e"),
                             {"e": USER_EMAIL})).mappings().first()
        uid, oid = u["id"], u["org_id"]

    r = redis.from_url("redis://redis:6379/0")
    queued = 0
    for sb in SYMBOLS:
        label = f"{sb}_5m_LO"
        sym = f"{sb}-USDT@BINANCEUS"
        src = build_source(label)
        v = validate_strategy_source(src)
        if not v.ok:
            print(f"SKIP {label}: {[e.as_dict() for e in v.errors][:1]}")
            continue
        name = f"_screen5m_{label}"
        async with sm() as s:
            if await get_user_strategy_by_name(s, user_id=uid, name=name) is None:
                await create_user_strategy(
                    s, user_id=uid, org_id=oid, name=name, description="5m 2yr crypto screen",
                    nl_description="5m 2yr crypto screen", class_name=v.class_name,
                    source_code=src, params_schema=v.params_schema, asset_class="crypto")
                await s.commit()
            bt_id = await create_backtest(
                s, user_id=uid, org_id=oid, strategy_name=name, params_json={},
                symbols=[sym], bar_resolution="5m", starting_cash=Decimal("25000"),
                fee_rate_bps=5, slippage_bps=3, window_start=WIN_START, window_end=WIN_END)
            await s.commit()
        await r.lpush(QUEUE_BACKTEST_JOBS, str(bt_id))
        queued += 1
        print(f"queued {label} bt={bt_id}")
    print(f"\nQUEUED {queued} 5m backtests over {WIN_START.date()} -> {WIN_END.date()}")


if __name__ == "__main__":
    asyncio.run(main())
