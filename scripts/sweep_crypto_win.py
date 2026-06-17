"""Refine the winning edge to >=3 trades/week while staying profitable.

Winner from sweep_crypto_ls.py: RSI(14) symmetric mean-reversion + SMA200 regime
filter (long dips ABOVE the 200-MA, short rallies BELOW it), exit to mid ->
+4.8%, pf 1.51, win 65%, maxDD -8% over BTC-USDT 1h 2025. But only 0.77 trades/wk.

The edge comes from the regime filter, NOT from a fast RSI (r2/r3 + filter
collapse to pf 0.62). So we raise frequency by WIDENING the entry bands (enter on
shallower dips/rallies) and modestly shortening RSI, keeping the SMA200 filter.
Search for the band/period that holds pf>1 at >=3 trades/wk.
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
PCT = 90.0

HEADER = '''"""WIN sweep candidate {name}."""
from __future__ import annotations
from pydantic import BaseModel
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class P(BaseModel):
    pass

'''


def ls_regime(rsi_p, lo, hi, le, se, sma_len):
    """RSI mean reversion + SMA regime filter, asymmetric exits.
    Long when RSI<lo AND price>SMA; exit long when RSI>le.
    Short when RSI>hi AND price<SMA; exit short when RSI<se."""
    body = f'''
class {{cls}}(Strategy[P]):
    PARAMS_MODEL = P
    RSI_P = {rsi_p}
    LO = {lo}
    HI = {hi}
    LE = {le}
    SE = {se}
    SMA_LEN = {sma_len}

    def on_init(self) -> None:
        self.symbol = self.symbols[0]

    def on_bar(self, ctx: BarContext) -> None:
        sym = self.symbol
        price = ctx.close(sym)
        rsi = ctx.rsi(sym, self.RSI_P)
        sma = ctx.sma(sym, self.SMA_LEN)
        if price is None or rsi is None or sma is None or float(price) <= 0:
            return
        r = float(rsi)
        px = float(price)
        sv = float(sma)
        pos = ctx.position(sym)
        if pos == 0:
            qty = ({PCT} / 100) * ctx.cash / price
            if qty <= 0:
                return
            if r < self.LO and px > sv:
                ctx.signal("regime_long", value=r, symbol=sym)
                ctx.submit_buy_market(sym, qty)
            elif r > self.HI and px < sv:
                ctx.signal("regime_short", value=r, symbol=sym)
                ctx.submit_sell_market(sym, qty)
        elif pos > 0:
            if r > self.LE:
                ctx.signal("regime_long_exit", value=r, symbol=sym)
                ctx.submit_sell_market(sym, pos)
        else:
            if r < self.SE:
                ctx.signal("regime_short_exit", value=r, symbol=sym)
                ctx.submit_buy_market(sym, -pos)
'''
    return body


CANDS = []
# (rsi_p, lo, hi, le, se, sma_len)
GRID = [
    (14, 35, 65, 50, 50, 200),   # baseline winner
    (14, 38, 62, 50, 50, 200),
    (14, 40, 60, 50, 50, 200),
    (14, 42, 58, 50, 50, 200),
    (14, 45, 55, 50, 50, 200),
    (12, 40, 60, 50, 50, 200),
    (12, 42, 58, 50, 50, 200),
    (12, 45, 55, 50, 50, 200),
    (10, 40, 60, 50, 50, 200),
    (10, 42, 58, 50, 50, 200),
    (10, 45, 55, 50, 50, 200),
    # faster regime MA (more in-regime flips -> more trades)
    (14, 40, 60, 50, 50, 150),
    (12, 42, 58, 50, 50, 150),
    (14, 40, 60, 50, 50, 100),
    # asymmetric exits: let winners run a bit past mid
    (14, 40, 60, 55, 45, 200),
    (12, 42, 58, 55, 45, 200),
]
for rsi_p, lo, hi, le, se, sma_len in GRID:
    tag = f"reg_r{rsi_p}_l{lo}_h{hi}_le{le}_se{se}_sma{sma_len}"
    CANDS.append((tag, ls_regime(rsi_p, lo, hi, le, se, sma_len)))


async def main():
    sm = get_sessionmaker()
    async with sm() as s:
        u = (await s.execute(text("SELECT id, org_id FROM users WHERE email=:e"),
                             {"e": USER_EMAIL})).mappings().first()
        uid, oid = u["id"], u["org_id"]

    jobs = []
    r = redis.from_url("redis://redis:6379/0")
    for tag, body in CANDS:
        cls = "S_" + tag.replace(".", "_")
        src = HEADER.format(name=tag) + body.format(cls=cls)
        v = validate_strategy_source(src)
        if not v.ok:
            print(f"SKIP {tag}: {[e.as_dict() for e in v.errors][:1]}")
            continue
        name = f"_winsweep_{tag}"
        async with sm() as s:
            if await get_user_strategy_by_name(s, user_id=uid, name=name) is None:
                await create_user_strategy(
                    s, user_id=uid, org_id=oid, name=name, description="win sweep",
                    nl_description="win sweep", class_name=v.class_name, source_code=src,
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

    pending = {bt for _, _, bt in jobs}
    for _ in range(180):
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
        for tag, name, bt in jobs:
            m = (await s.execute(text(
                "SELECT status, num_closed_trades, "
                "(analysis_json->'metrics'->>'total_return_pct') ret, "
                "(analysis_json->'metrics'->>'profit_factor') pf, "
                "(analysis_json->'metrics'->>'win_rate_pct') wr, "
                "(analysis_json->'metrics'->>'max_drawdown_pct') dd, "
                "(analysis_json->'metrics'->>'sharpe') sh "
                "FROM backtests WHERE id=:b"), {"b": bt})).mappings().first()
            n = m["num_closed_trades"] or 0
            ret = float(m["ret"]) if m["ret"] is not None else None
            results.append({
                "tag": tag, "status": m["status"], "n": n, "tpw": n / WEEKS,
                "ret": ret, "pf": m["pf"], "wr": m["wr"], "dd": m["dd"],
                "sh": m["sh"], "bt": bt})

    def keyf(rr):
        meets = rr["tpw"] >= 3 and (rr["ret"] or -1) > 0
        return (meets, rr["ret"] if rr["ret"] is not None else -1e9)
    results.sort(key=keyf, reverse=True)
    print(f"\n{'tag':36} {'tpw':>5} {'trd':>5} {'ret%':>8} {'pf':>5} {'win%':>5} {'dd%':>6} {'sharpe':>7} 3/wk")
    for rr in results:
        mark = "Y" if rr["tpw"] >= 3 else "."
        ret = f"{rr['ret']:.1f}" if rr["ret"] is not None else "n/a"
        pf = f"{float(rr['pf']):.2f}" if rr["pf"] else "n/a"
        wr = f"{float(rr['wr']):.0f}" if rr["wr"] else "n/a"
        dd = f"{float(rr['dd']):.1f}" if rr["dd"] else "n/a"
        sh = f"{float(rr['sh']):.2f}" if rr["sh"] else "n/a"
        print(f"{rr['tag']:36} {rr['tpw']:5.2f} {rr['n']:5d} {ret:>8} {pf:>5} {wr:>5} {dd:>6} {sh:>7}   {mark}")

    winners = [rr for rr in results if rr["tpw"] >= 3 and (rr["ret"] or -1) > 0]
    print(f"\nPROFITABLE & >=3/wk: {len(winners)}")
    for w in sorted(winners, key=lambda x: float(x["pf"] or 0), reverse=True):
        print(f"  {w['tag']}  tpw={w['tpw']:.2f} ret={w['ret']:.1f}% pf={w['pf']} dd={w['dd']} bt={w['bt']}")


if __name__ == "__main__":
    asyncio.run(main())
