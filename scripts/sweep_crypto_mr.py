"""Mean-reversion sweep on BTC-USDT 1h (2025): Connors-style short-period RSI
dip-buy variants, looking for one that is BOTH >=3 trades/week AND profitable.

Diagnosis from sweep_crypto.py: trend-following bleeds 30-50% on BTC 1h (chop +
fees), while RSI(14) mean-reversion is ~breakeven (pf~1.0, win~60-67%) but trades
<1/wk. This sweep raises mean-reversion frequency with RSI(2-4) and adds optional
ATR-free fixed stop/take-profit to cap the mean-reversion tail losses.

Builds each as a real user_strategy, runs the real backtest engine + queue, ranks.
Temp strategies are named '_mrsweep_<...>'.
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

HEADER = '''"""MR sweep candidate {name}."""
from __future__ import annotations
from pydantic import BaseModel
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class P(BaseModel):
    pass

'''


def mr_dip(rsi_p, entry, tp, sl, ema_len):
    """Connors-style dip buy. ema_len=0 disables the trend filter; tp/sl=0
    disables that exit. Always exits when close rises back above SMA(5)."""
    body = f'''
class {{cls}}(Strategy[P]):
    PARAMS_MODEL = P
    RSI_P = {rsi_p}
    ENTRY = {entry}
    TP = {tp}
    SL = {sl}
    EMA_LEN = {ema_len}

    def on_init(self) -> None:
        self.symbol = self.symbols[0]
        self.state["entry_px"] = None

    def on_bar(self, ctx: BarContext) -> None:
        sym = self.symbol
        price = ctx.close(sym)
        rsi = ctx.rsi(sym, self.RSI_P)
        if price is None or rsi is None:
            return
        pos = ctx.position(sym)
        sma5 = ctx.sma(sym, 5)
        if pos == 0:
            ok_trend = True
            if self.EMA_LEN > 0:
                ema = ctx.ema(sym, self.EMA_LEN)
                if ema is None:
                    return
                ok_trend = float(price) > float(ema)
            if ok_trend and float(rsi) < self.ENTRY and float(price) > 0:
                qty = ({PCT} / 100) * ctx.cash / price
                if qty > 0:
                    ctx.signal("mr_dip_buy", value=float(rsi), symbol=sym)
                    ctx.submit_buy_market(sym, qty)
                    self.state["entry_px"] = float(price)
        else:
            ep = self.state["entry_px"]
            exit_now = False
            if ep is not None and ep > 0:
                if self.TP > 0 and float(price) >= ep * (1 + self.TP):
                    exit_now = True
                elif self.SL > 0 and float(price) <= ep * (1 - self.SL):
                    exit_now = True
            if not exit_now and sma5 is not None and float(price) > float(sma5):
                exit_now = True
            if exit_now:
                ctx.signal("mr_dip_sell", value=float(rsi), symbol=sym)
                ctx.submit_sell_market(sym, pos)
                self.state["entry_px"] = None
'''
    return body


CANDS = []
# (rsi_p, entry, tp, sl, ema_len)
GRID = [
    (2, 5, 0.0, 0.0, 200),
    (2, 10, 0.0, 0.0, 200),
    (2, 15, 0.0, 0.0, 200),
    (2, 10, 0.0, 0.0, 100),
    (2, 15, 0.0, 0.0, 100),
    (2, 10, 0.0, 0.0, 0),
    (2, 15, 0.0, 0.0, 0),
    (3, 15, 0.0, 0.0, 200),
    (3, 20, 0.0, 0.0, 200),
    (3, 15, 0.0, 0.0, 100),
    (3, 25, 0.0, 0.0, 100),
    (3, 20, 0.0, 0.0, 0),
    (4, 20, 0.0, 0.0, 200),
    (4, 25, 0.0, 0.0, 100),
    (4, 30, 0.0, 0.0, 100),
    # stop-loss / take-profit variants on higher-frequency entries
    (2, 15, 0.0, 0.05, 100),
    (3, 20, 0.0, 0.05, 100),
    (2, 10, 0.03, 0.04, 200),
    (3, 20, 0.025, 0.04, 0),
    (2, 15, 0.02, 0.03, 100),
]
for rsi_p, entry, tp, sl, ema_len in GRID:
    tag = f"mrdip_r{rsi_p}_e{entry}_tp{int(tp*1000)}_sl{int(sl*1000)}_em{ema_len}"
    CANDS.append((tag, mr_dip(rsi_p, entry, tp, sl, ema_len)))


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
        name = f"_mrsweep_{tag}"
        async with sm() as s:
            if await get_user_strategy_by_name(s, user_id=uid, name=name) is None:
                await create_user_strategy(
                    s, user_id=uid, org_id=oid, name=name, description="mr sweep",
                    nl_description="mr sweep", class_name=v.class_name, source_code=src,
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
    for _ in range(150):
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
        return (rr["tpw"] >= 3, rr["ret"] if rr["ret"] is not None else -1e9)
    results.sort(key=keyf, reverse=True)
    print(f"\n{'tag':40} {'tpw':>5} {'trd':>5} {'ret%':>8} {'pf':>5} {'win%':>5} {'dd%':>6} 3/wk")
    for rr in results:
        mark = "Y" if rr["tpw"] >= 3 else "."
        ret = f"{rr['ret']:.1f}" if rr["ret"] is not None else "n/a"
        pf = f"{float(rr['pf']):.2f}" if rr["pf"] else "n/a"
        wr = f"{float(rr['wr']):.0f}" if rr["wr"] else "n/a"
        dd = f"{float(rr['dd']):.1f}" if rr["dd"] else "n/a"
        print(f"{rr['tag']:40} {rr['tpw']:5.2f} {rr['n']:5d} {ret:>8} {pf:>5} {wr:>5} {dd:>6}   {mark}")

    winners = [rr for rr in results if rr["tpw"] >= 3 and (rr["ret"] or -1) > 0]
    print(f"\nPROFITABLE & >=3/wk: {len(winners)}")
    for w in sorted(winners, key=lambda x: x["ret"], reverse=True):
        print(f"  {w['tag']}  tpw={w['tpw']:.2f} ret={w['ret']:.1f}% pf={w['pf']} bt={w['bt']}")


if __name__ == "__main__":
    asyncio.run(main())
