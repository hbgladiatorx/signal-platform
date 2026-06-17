"""Deploy the per-symbol tuned regime-reversion winners as first-class user
strategies, each verified over full-2025 + H1/H2 splits.

Fill WINNERS from tune_crypto_multi.py output. Each entry bakes its tuned
parameters as Field defaults so the deployed strategy is self-documenting and
runs the right config out of the box (symbol/timeframe bound at backtest/live
time). long_only drops the short side for coins that trended (where shorting
below the SMA blew up).
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

# Filled from the tuning sweep. Each: name, symbol, timeframe, and tuned params.
# direction "ls" = long+short, "long" = long-only.
WINNERS: list[dict] = [
    # LINK long-only: best risk-adjusted of the whole sweep (+79%, PF 2.09, DD -18%).
    {"name": "LINK Regime Reversion 1h", "symbol": "LINK-USDT@BINANCEUS", "tf": "1h",
     "rsi": 14, "lo": 42, "hi": 58, "le": 60, "se": 40, "sma": 200,
     "tp": 0.040, "sl": 0.06, "long_only": True},
    # LINK long/short: higher-octane variant (+101%, PF 1.49, DD -32%).
    {"name": "LINK Regime Reversion 1h (Long/Short)", "symbol": "LINK-USDT@BINANCEUS", "tf": "1h",
     "rsi": 14, "lo": 43, "hi": 57, "le": 55, "se": 45, "sma": 200,
     "tp": 0.030, "sl": 0.06, "long_only": False},
    # BNB long-only: cleanest profile, shallow -9% drawdown (+11.6%, PF 1.44).
    {"name": "BNB Regime Reversion 1h", "symbol": "BNB-USDT@BINANCEUS", "tf": "1h",
     "rsi": 14, "lo": 42, "hi": 58, "le": 55, "se": 45, "sma": 200,
     "tp": 0.030, "sl": 0.05, "long_only": True},
]


def make_source(w: dict) -> str:
    long_only = w["long_only"]
    desc = (
        f"Regime-filtered RSI({w['rsi']}) mean reversion "
        f"({'long-only' if long_only else 'long/short'}) on {w['symbol'].split('@')[0]} "
        f"{w['tf']}, SMA{w['sma']} regime filter, "
        f"{w['tp']*100:.2f}% take-profit / {w['sl']*100:.2f}% stop."
    )
    short_field = "" if long_only else f'''
    entry_short: float = Field(default={w['hi']}.0, ge=50, le=99,
                               description="Short when RSI rises above this (and below the SMA).")
    exit_short: float = Field(default={w['se']}.0, ge=1, le=50,
                              description="Exit a short when RSI falls below this.")'''
    short_validate = "" if long_only else '''
        if self.entry_long >= self.entry_short:
            raise ValueError("entry_long must be below entry_short")'''
    short_entry = "" if long_only else '''
            elif r > p.entry_short and px < sv:
                ctx.signal("regime_short", value=r, symbol=sym)
                ctx.submit_sell_market(sym, qty)
                self.state["entry_px"] = px'''
    short_exit = "" if long_only else '''
        else:
            ep = self.state["entry_px"]
            tp_hit = p.take_profit_pct > 0 and ep is not None and px <= ep * (1 - p.take_profit_pct)
            sl_hit = p.stop_loss_pct > 0 and ep is not None and px >= ep * (1 + p.stop_loss_pct)
            if r < p.exit_short or tp_hit or sl_hit:
                ctx.signal("regime_short_exit", value=r, symbol=sym)
                ctx.submit_buy_market(sym, -pos)
                self.state["entry_px"] = None'''
    return f'''"""{desc}"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class RegimeReversionParams(BaseModel):
    """Tuned regime-filtered mean-reversion parameters."""

    model_config = {{"extra": "forbid"}}

    rsi_period: int = Field(default={w['rsi']}, ge=2, le=100)
    sma_period: int = Field(default={w['sma']}, ge=20, le=1000,
                            description="Regime filter: SMA lookback in bars.")
    entry_long: float = Field(default={w['lo']}.0, ge=1, le=50,
                              description="Go long when RSI dips below this (and above the SMA).")
    exit_long: float = Field(default={w['le']}.0, ge=50, le=99,
                             description="Exit a long when RSI recovers above this."){short_field}
    take_profit_pct: float = Field(default={w['tp']}, ge=0, le=0.5,
                                   description="Bank profit at this fraction from entry.")
    stop_loss_pct: float = Field(default={w['sl']}, ge=0, le=0.5,
                                 description="Cap loss at this fraction from entry (0 disables).")
    position_pct: float = Field(default=90.0, gt=0, le=100,
                                description="Percent of available cash deployed per entry.")

    @model_validator(mode="after")
    def _check(self) -> "RegimeReversionParams":{short_validate or """
        pass"""}
        return self


class RegimeReversion(Strategy[RegimeReversionParams]):
    """Tuned regime-filtered RSI mean reversion, single symbol."""

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
        if pos == 0:
            qty = (p.position_pct / 100.0) * ctx.cash / price
            if qty <= 0:
                return
            if r < p.entry_long and px > sv:
                ctx.signal("regime_long", value=r, symbol=sym)
                ctx.submit_buy_market(sym, qty)
                self.state["entry_px"] = px{short_entry}
        elif pos > 0:
            ep = self.state["entry_px"]
            tp_hit = p.take_profit_pct > 0 and ep is not None and px >= ep * (1 + p.take_profit_pct)
            sl_hit = p.stop_loss_pct > 0 and ep is not None and px <= ep * (1 - p.stop_loss_pct)
            if r > p.exit_long or tp_hit or sl_hit:
                ctx.signal("regime_long_exit", value=r, symbol=sym)
                ctx.submit_sell_market(sym, pos)
                self.state["entry_px"] = None{short_exit}
'''


def windows():
    return [
        ("full2025", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ("H1", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)),
        ("H2", datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ]


async def main():
    if not WINNERS:
        print("WINNERS is empty — fill it from the tuning sweep first.")
        return
    sm = get_sessionmaker()
    async with sm() as s:
        u = (await s.execute(text("SELECT id, org_id FROM users WHERE email=:e"),
                             {"e": USER_EMAIL})).mappings().first()
        uid, oid = u["id"], u["org_id"]

    r = redis.from_url("redis://redis:6379/0")
    jobs = []
    for w in WINNERS:
        src = make_source(w)
        v = validate_strategy_source(src)
        if not v.ok:
            print(f"VALIDATION FAILED {w['name']}:", [e.as_dict() for e in v.errors][:2])
            continue
        async with sm() as s:
            existing = await get_user_strategy_by_name(s, user_id=uid, name=w["name"])
            if existing is None:
                sid = await create_user_strategy(
                    s, user_id=uid, org_id=oid, name=w["name"],
                    description=f"Tuned regime-reversion on {w['symbol'].split('@')[0]} {w['tf']}.",
                    nl_description="Buy RSI dips with the trend, bank a quick bounce, hard stop.",
                    class_name=v.class_name, source_code=src,
                    params_schema=v.params_schema, asset_class="crypto")
                await s.commit()
                print(f"created {w['name']} -> {sid}")
            else:
                print(f"exists  {w['name']}")
        for tag, ws, we in windows():
            async with sm() as s:
                bt_id = await create_backtest(
                    s, user_id=uid, org_id=oid, strategy_name=w["name"], params_json={},
                    symbols=[w["symbol"]], bar_resolution=w["tf"], starting_cash=Decimal("25000"),
                    fee_rate_bps=5, slippage_bps=3, window_start=ws, window_end=we)
                await s.commit()
            await r.lpush(QUEUE_BACKTEST_JOBS, str(bt_id))
            jobs.append((w["name"], tag, str(bt_id)))
    print(f"queued {len(jobs)} verification backtests")

    pending = {bt for _, _, bt in jobs}
    for _ in range(240):
        await asyncio.sleep(4)
        async with sm() as s:
            rows = (await s.execute(text(
                "SELECT id::text id, status FROM backtests WHERE id = ANY(:ids)"),
                {"ids": list(pending)})).mappings().all()
        pending -= {row["id"] for row in rows if row["status"] in ("completed", "failed")}
        if not pending:
            break
    print(f"unfinished: {len(pending)}\n")

    async with sm() as s:
        for name, tag, bt in jobs:
            m = (await s.execute(text(
                "SELECT status, num_closed_trades n, "
                "(analysis_json->'metrics'->>'total_return_pct') ret, "
                "(analysis_json->'metrics'->>'profit_factor') pf, "
                "(analysis_json->'metrics'->>'win_rate_pct') wr, "
                "(analysis_json->'metrics'->>'max_drawdown_pct') dd, "
                "(analysis_json->'metrics'->>'sharpe') sh "
                "FROM backtests WHERE id=:b"), {"b": bt})).mappings().first()
            ret = f"{float(m['ret']):.1f}%" if m["ret"] else "n/a"
            pf = f"{float(m['pf']):.2f}" if m["pf"] else "n/a"
            wr = f"{float(m['wr']):.0f}" if m["wr"] else "n/a"
            dd = f"{float(m['dd']):.0f}" if m["dd"] else "n/a"
            sh = f"{float(m['sh']):.2f}" if m["sh"] else "n/a"
            print(f"{name:34} {tag:8} {m['status']:9} trd={m['n'] or 0:4d} ret={ret:>7} "
                  f"pf={pf:>5} win={wr:>3} dd={dd:>4} sharpe={sh:>5}")


if __name__ == "__main__":
    asyncio.run(main())
