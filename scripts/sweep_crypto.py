"""Sweep crypto strategy candidates on BTC-USDT 1h (2025) to find one that is
BOTH >=3 trades/week AND profitable. Builds each as a real user_strategy, runs
it through the backtest engine + queue, and ranks the results.

Temp strategies are named '_sweep_<...>' so they can be cleaned up afterward.
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
WIN_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
WIN_END = datetime(2026, 1, 1, tzinfo=timezone.utc)
WEEKS = (WIN_END - WIN_START).days / 7.0
PCT = 95.0

HEADER = '''"""Sweep candidate {name}."""
from __future__ import annotations
from pydantic import BaseModel
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class P(BaseModel):
    pass

'''


def ema_cross(fast, slow):
    body = f'''
class {{cls}}(Strategy[P]):
    PARAMS_MODEL = P
    FAST = {fast}
    SLOW = {slow}

    def on_init(self) -> None:
        self.symbol = self.symbols[0]
        self.state["pf"] = None
        self.state["ps"] = None

    def on_bar(self, ctx: BarContext) -> None:
        fast = ctx.ema(self.symbol, self.FAST)
        slow = ctx.ema(self.symbol, self.SLOW)
        if fast is None or slow is None:
            return
        pf = self.state["pf"]
        ps = self.state["ps"]
        pos = ctx.position(self.symbol)
        if pf is not None and ps is not None:
            if pos == 0 and float(pf) <= float(ps) and float(fast) > float(slow):
                price = ctx.close(self.symbol)
                if price is not None and price > 0:
                    qty = ({PCT} / 100) * ctx.cash / price
                    if qty > 0:
                        ctx.signal("ema_cross_up", value=float(fast), symbol=self.symbol)
                        ctx.submit_buy_market(self.symbol, qty)
            elif pos > 0 and float(pf) >= float(ps) and float(fast) < float(slow):
                ctx.signal("ema_cross_dn", value=float(fast), symbol=self.symbol)
                ctx.submit_sell_market(self.symbol, pos)
        self.state["pf"] = fast
        self.state["ps"] = slow
'''
    return body


def rsi_mom(period, hi, lo):
    body = f'''
class {{cls}}(Strategy[P]):
    PARAMS_MODEL = P
    PERIOD = {period}
    HI = {hi}
    LO = {lo}

    def on_init(self) -> None:
        self.symbol = self.symbols[0]
        self.state["prev"] = None

    def on_bar(self, ctx: BarContext) -> None:
        rsi = ctx.rsi(self.symbol, self.PERIOD)
        if rsi is None:
            return
        prev = self.state["prev"]
        pos = ctx.position(self.symbol)
        if prev is not None:
            if pos == 0 and float(prev) <= self.HI and float(rsi) > self.HI:
                price = ctx.close(self.symbol)
                if price is not None and price > 0:
                    qty = ({PCT} / 100) * ctx.cash / price
                    if qty > 0:
                        ctx.signal("rsi_mom_up", value=float(rsi), symbol=self.symbol)
                        ctx.submit_buy_market(self.symbol, qty)
            elif pos > 0 and float(prev) >= self.LO and float(rsi) < self.LO:
                ctx.signal("rsi_mom_dn", value=float(rsi), symbol=self.symbol)
                ctx.submit_sell_market(self.symbol, pos)
        self.state["prev"] = rsi
'''
    return body


def mr_trend(period, entry, exit_, ema_len):
    body = f'''
class {{cls}}(Strategy[P]):
    PARAMS_MODEL = P
    PERIOD = {period}
    ENTRY = {entry}
    EXIT = {exit_}
    EMA_LEN = {ema_len}

    def on_init(self) -> None:
        self.symbol = self.symbols[0]

    def on_bar(self, ctx: BarContext) -> None:
        rsi = ctx.rsi(self.symbol, self.PERIOD)
        emaf = ctx.ema(self.symbol, self.EMA_LEN)
        price = ctx.close(self.symbol)
        if rsi is None or emaf is None or price is None:
            return
        pos = ctx.position(self.symbol)
        if pos == 0 and float(rsi) < self.ENTRY and float(price) > float(emaf):
            if price > 0:
                qty = ({PCT} / 100) * ctx.cash / price
                if qty > 0:
                    ctx.signal("mr_trend_entry", value=float(rsi), symbol=self.symbol)
                    ctx.submit_buy_market(self.symbol, qty)
        elif pos > 0 and float(rsi) > self.EXIT:
            ctx.signal("mr_trend_exit", value=float(rsi), symbol=self.symbol)
            ctx.submit_sell_market(self.symbol, pos)
'''
    return body


# (tag, builder)
CANDS = []
for f, s in [(5, 15), (7, 21), (9, 26), (6, 20), (8, 34), (12, 26), (10, 40), (4, 12)]:
    CANDS.append((f"emax_{f}_{s}", ema_cross(f, s)))
for p, hi, lo in [(14, 55, 45), (10, 55, 45), (14, 60, 40), (10, 60, 50), (7, 55, 45)]:
    CANDS.append((f"rsimom_{p}_{hi}_{lo}", rsi_mom(p, hi, lo)))
for p, e, x, el in [(14, 43, 48, 200), (14, 40, 55, 200), (10, 42, 50, 100),
                    (14, 35, 50, 100), (14, 45, 55, 300)]:
    CANDS.append((f"mrtr_{p}_{e}_{x}_{el}", mr_trend(p, e, x, el)))


async def main():
    sm = get_sessionmaker()
    async with sm() as s:
        u = (await s.execute(text("SELECT id, org_id FROM users WHERE email=:e"),
                             {"e": USER_EMAIL})).mappings().first()
        uid, oid = u["id"], u["org_id"]

    jobs = []  # (tag, name, bt_id)
    r = redis.from_url("redis://redis:6379/0")
    for tag, body in CANDS:
        cls = "S_" + tag.replace(".", "_")
        src = HEADER.format(name=tag) + body.format(cls=cls)
        v = validate_strategy_source(src)
        if not v.ok:
            print(f"SKIP {tag}: validation failed {[e.as_dict() for e in v.errors][:1]}")
            continue
        name = f"_sweep_{tag}"
        async with sm() as s:
            if await get_user_strategy_by_name(s, user_id=uid, name=name) is None:
                await create_user_strategy(
                    s, user_id=uid, org_id=oid, name=name, description="sweep",
                    nl_description="sweep", class_name=v.class_name, source_code=src,
                    params_schema=v.params_schema, asset_class="crypto")
                await s.commit()
            bt_id = await create_backtest(
                s, user_id=uid, org_id=oid, strategy_name=name, params_json={},
                symbols=[SYMBOL], bar_resolution="1h", starting_cash=Decimal("25000"),
                fee_rate_bps=5, slippage_bps=3, window_start=WIN_START, window_end=WIN_END)
            await s.commit()
        await r.lpush(QUEUE_BACKTEST_JOBS, str(bt_id))
        jobs.append((tag, name, str(bt_id)))
    print(f"queued {len(jobs)} backtests")

    # Poll all to terminal.
    pending = {bt for _, _, bt in jobs}
    for _ in range(120):
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

    # Collect + rank.
    results = []
    async with sm() as s:
        for tag, name, bt in jobs:
            m = (await s.execute(text(
                "SELECT status, num_closed_trades, "
                "(analysis_json->'metrics'->>'total_return_pct') ret, "
                "(analysis_json->'metrics'->>'profit_factor') pf, "
                "(analysis_json->'metrics'->>'win_rate_pct') wr, "
                "(analysis_json->'metrics'->>'sharpe') sh "
                "FROM backtests WHERE id=:b"), {"b": bt})).mappings().first()
            n = m["num_closed_trades"] or 0
            ret = float(m["ret"]) if m["ret"] is not None else None
            results.append({
                "tag": tag, "status": m["status"], "n": n, "tpw": n / WEEKS,
                "ret": ret, "pf": m["pf"], "wr": m["wr"], "sh": m["sh"], "bt": bt})

    def keyf(r):
        meets = r["tpw"] >= 3
        return (meets, r["ret"] if r["ret"] is not None else -1e9)
    results.sort(key=keyf, reverse=True)
    print(f"\n{'tag':24} {'tpw':>6} {'trades':>7} {'return%':>9} {'pf':>6} {'win%':>6}  3/wk")
    for r in results:
        mark = "Y" if r["tpw"] >= 3 else "."
        ret = f"{r['ret']:.1f}" if r["ret"] is not None else "n/a"
        pf = f"{float(r['pf']):.2f}" if r["pf"] else "n/a"
        wr = f"{float(r['wr']):.0f}" if r["wr"] else "n/a"
        print(f"{r['tag']:24} {r['tpw']:6.2f} {r['n']:7d} {ret:>9} {pf:>6} {wr:>6}   {mark}")

    winners = [r for r in results if r["tpw"] >= 3 and (r["ret"] or -1) > 0]
    print(f"\nPROFITABLE & >=3/wk: {len(winners)}")
    for w in winners[:5]:
        print(f"  {w['tag']}  tpw={w['tpw']:.2f} ret={w['ret']:.1f}% bt={w['bt']}")


if __name__ == "__main__":
    asyncio.run(main())
