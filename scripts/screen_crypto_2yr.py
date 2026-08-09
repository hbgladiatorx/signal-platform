"""Screen the regime-reversion edge across the full crypto universe on a FULL
2-YEAR window.

28 Binance.US spot pairs have complete 1h history from 2024-01-01 onward, so we
run every one of them over an exact 2-year window (2024-06-15 -> 2026-06-15).
The strategy = the proven RSI(14) mean-reversion + SMA200 regime filter, run
long-only (spot-realistic, with a hard stop) plus two long/short variants on the
deepest pairs (BTC, ETH). 28 + 2 = 30 backtests.

Long-only band: entry RSI<42 above SMA200, exit RSI>60, tp 4% / sl 6%, pos 90%.
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
WEEKS = (WIN_END - WIN_START).days / 7.0

# 28 pairs with verified full 2-year 1h coverage (cagg_bars_1h, crypto_spot).
SYMBOLS = [
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "LTC",
    "XLM", "NEAR", "HBAR", "FET", "SUI", "ALGO", "BCH", "DOT", "SHIB", "ATOM",
    "ICP", "FIL", "UNI", "OP", "ARB", "ETC", "AAVE", "APT",
]


def build_source(name: str, long_only: bool,
                 rsi=14, sma=200, lo=42, le=60, hi=57, se=45,
                 tp=0.04, sl=0.06) -> str:
    short_field = "" if long_only else f'''
    entry_short: float = Field(default={hi}.0, ge=50, le=99)
    exit_short: float = Field(default={se}.0, ge=1, le=50)'''
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
    return f'''"""SCREEN 2yr {name}."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class P(BaseModel):
    model_config = {{"extra": "forbid"}}

    rsi_period: int = Field(default={rsi}, ge=2, le=100)
    sma_period: int = Field(default={sma}, ge=20, le=1000)
    entry_long: float = Field(default={lo}.0, ge=1, le=50)
    exit_long: float = Field(default={le}.0, ge=50, le=99){short_field}
    take_profit_pct: float = Field(default={tp}, ge=0, le=0.5)
    stop_loss_pct: float = Field(default={sl}, ge=0, le=0.5)
    position_pct: float = Field(default=90.0, gt=0, le=100)

    @model_validator(mode="after")
    def _check(self) -> "P":{short_validate or """
        pass"""}
        return self


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


def grid():
    g = []
    for s in SYMBOLS:
        g.append((f"{s}_2yr_LO", f"{s}-USDT@BINANCEUS", True))
    # two long/short variants on the deepest pairs -> 30 total
    g.append(("BTC_2yr_LS", "BTC-USDT@BINANCEUS", False))
    g.append(("ETH_2yr_LS", "ETH-USDT@BINANCEUS", False))
    return g


async def main():
    sm = get_sessionmaker()
    async with sm() as s:
        u = (await s.execute(text("SELECT id, org_id FROM users WHERE email=:e"),
                             {"e": USER_EMAIL})).mappings().first()
        uid, oid = u["id"], u["org_id"]

    r = redis.from_url("redis://redis:6379/0")
    jobs = []
    for label, sym, long_only in grid():
        src = build_source(label, long_only)
        v = validate_strategy_source(src)
        if not v.ok:
            print(f"SKIP {label}: {[e.as_dict() for e in v.errors][:1]}")
            continue
        name = f"_screen2yr_{label}"
        async with sm() as s:
            if await get_user_strategy_by_name(s, user_id=uid, name=name) is None:
                await create_user_strategy(
                    s, user_id=uid, org_id=oid, name=name, description="2yr crypto screen",
                    nl_description="2yr crypto screen", class_name=v.class_name, source_code=src,
                    params_schema=v.params_schema, asset_class="crypto")
                await s.commit()
            bt_id = await create_backtest(
                s, user_id=uid, org_id=oid, strategy_name=name, params_json={},
                symbols=[sym], bar_resolution="1h", starting_cash=Decimal("25000"),
                fee_rate_bps=5, slippage_bps=3, window_start=WIN_START, window_end=WIN_END)
            await s.commit()
        await r.lpush(QUEUE_BACKTEST_JOBS, str(bt_id))
        jobs.append((label, sym, str(bt_id)))
    print(f"queued {len(jobs)} backtests over {WIN_START.date()} -> {WIN_END.date()} "
          f"({(WIN_END - WIN_START).days / 365.25:.2f}yr)")

    pending = {bt for _, _, bt in jobs}
    for _ in range(450):
        await asyncio.sleep(4)
        async with sm() as s:
            rows = (await s.execute(text(
                "SELECT id::text id, status FROM backtests WHERE id = ANY(:ids)"),
                {"ids": list(pending)})).mappings().all()
        done = {row["id"] for row in rows if row["status"] in ("completed", "failed")}
        pending -= done
        if not pending:
            break
    print(f"unfinished: {len(pending)}")

    results = []
    async with sm() as s:
        for label, sym, bt in jobs:
            m = (await s.execute(text(
                "SELECT status, num_closed_trades n, "
                "(analysis_json->'metrics'->>'total_return_pct') ret, "
                "(analysis_json->'metrics'->>'profit_factor') pf, "
                "(analysis_json->'metrics'->>'win_rate_pct') wr, "
                "(analysis_json->'metrics'->>'max_drawdown_pct') dd, "
                "(analysis_json->'metrics'->>'sharpe') sh "
                "FROM backtests WHERE id=:b"), {"b": bt})).mappings().first()
            n = m["n"] or 0
            results.append({
                "label": label, "sym": sym, "status": m["status"], "n": n,
                "tpw": n / WEEKS,
                "ret": float(m["ret"]) if m["ret"] is not None else None,
                "pf": float(m["pf"]) if m["pf"] else None,
                "wr": float(m["wr"]) if m["wr"] else None,
                "dd": float(m["dd"]) if m["dd"] else None,
                "sh": float(m["sh"]) if m["sh"] else None, "bt": bt})

    def good(rr):
        return (rr["ret"] or -1) > 0 and (rr["pf"] or 0) >= 1.1 and rr["n"] >= 20

    results.sort(key=lambda rr: (good(rr), rr["pf"] or -1), reverse=True)
    print(f"\n{'label':16} {'tpw':>5} {'trd':>4} {'ret%':>8} {'pf':>5} {'win':>4} {'dd':>6} {'shrp':>5} ok stat")
    for rr in results:
        ret = f"{rr['ret']:.1f}" if rr["ret"] is not None else "n/a"
        pf = f"{rr['pf']:.2f}" if rr["pf"] else "n/a"
        wr = f"{rr['wr']:.0f}" if rr["wr"] else "n/a"
        dd = f"{rr['dd']:.0f}" if rr["dd"] else "n/a"
        sh = f"{rr['sh']:.2f}" if rr["sh"] else "n/a"
        print(f"{rr['label']:16} {rr['tpw']:5.2f} {rr['n']:4d} {ret:>8} {pf:>5} {wr:>4} "
              f"{dd:>6} {sh:>5}  {'Y' if good(rr) else '.'}  {rr['status'][:4]}")

    winners = [rr for rr in results if good(rr)]
    print(f"\nPROFITABLE (ret>0, pf>=1.1, >=20 trd): {len(winners)} / {len(results)}")
    for w in winners:
        print(f"  WIN {w['label']:16} ret={w['ret']:.1f}% pf={w['pf']:.2f} "
              f"tpw={w['tpw']:.2f} dd={w['dd']:.0f}% sharpe={w['sh']:.2f} bt={w['bt']}")


if __name__ == "__main__":
    asyncio.run(main())
