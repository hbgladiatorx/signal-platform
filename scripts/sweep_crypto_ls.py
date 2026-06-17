"""Long/SHORT mean-reversion sweep on BTC-USDT 1h (2025).

Key finding from earlier sweeps: BTC buy&hold over this window was -6.9% (flat/
down, choppy). Long-only strategies (trend OR mean-reversion) all lose because
there is no uptrend to revert into. Shorting is enabled by default in the engine
(allow_short=True), so a SYMMETRIC oscillator mean-reversion that also shorts
overbought rallies can harvest the downswings a down/sideways market provides.

Design: RSI(p) band. Flat -> go long when RSI<LO, go short when RSI>HI. Exit the
position back to flat when RSI reverts through EXIT (mid). Optional regime filter
(SMA200: only long above / only short below) and optional fixed stop-loss.
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

HEADER = '''"""LS sweep candidate {name}."""
from __future__ import annotations
from pydantic import BaseModel
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class P(BaseModel):
    pass

'''


def ls_mr(rsi_p, lo, hi, exit_mid, ema_len, sl):
    """Symmetric long/short RSI mean reversion. ema_len=0 disables regime
    filter; sl=0 disables stop. Exits to flat when RSI reverts through mid."""
    body = f'''
class {{cls}}(Strategy[P]):
    PARAMS_MODEL = P
    RSI_P = {rsi_p}
    LO = {lo}
    HI = {hi}
    MID = {exit_mid}
    EMA_LEN = {ema_len}
    SL = {sl}

    def on_init(self) -> None:
        self.symbol = self.symbols[0]
        self.state["entry_px"] = None

    def on_bar(self, ctx: BarContext) -> None:
        sym = self.symbol
        price = ctx.close(sym)
        rsi = ctx.rsi(sym, self.RSI_P)
        if price is None or rsi is None or float(price) <= 0:
            return
        r = float(rsi)
        px = float(price)
        pos = ctx.position(sym)
        ema = None
        if self.EMA_LEN > 0:
            ema = ctx.ema(sym, self.EMA_LEN)
            if ema is None:
                return
        if pos == 0:
            qty = ({PCT} / 100) * ctx.cash / price
            if qty <= 0:
                return
            long_ok = ema is None or px > float(ema)
            short_ok = ema is None or px < float(ema)
            if r < self.LO and long_ok:
                ctx.signal("ls_long", value=r, symbol=sym)
                ctx.submit_buy_market(sym, qty)
                self.state["entry_px"] = px
            elif r > self.HI and short_ok:
                ctx.signal("ls_short", value=r, symbol=sym)
                ctx.submit_sell_market(sym, qty)
                self.state["entry_px"] = px
        elif pos > 0:
            ep = self.state["entry_px"]
            stop_hit = self.SL > 0 and ep is not None and px <= ep * (1 - self.SL)
            if r > self.MID or stop_hit:
                ctx.signal("ls_long_exit", value=r, symbol=sym)
                ctx.submit_sell_market(sym, pos)
                self.state["entry_px"] = None
        else:
            ep = self.state["entry_px"]
            stop_hit = self.SL > 0 and ep is not None and px >= ep * (1 + self.SL)
            if r < self.MID or stop_hit:
                ctx.signal("ls_short_exit", value=r, symbol=sym)
                ctx.submit_buy_market(sym, -pos)
                self.state["entry_px"] = None
'''
    return body


CANDS = []
# (rsi_p, lo, hi, mid, ema_len, sl)
GRID = [
    # symmetric, no regime filter
    (2, 10, 90, 50, 0, 0.0),
    (2, 15, 85, 50, 0, 0.0),
    (2, 20, 80, 50, 0, 0.0),
    (3, 15, 85, 50, 0, 0.0),
    (3, 20, 80, 50, 0, 0.0),
    (3, 25, 75, 50, 0, 0.0),
    (7, 25, 75, 50, 0, 0.0),
    (7, 30, 70, 50, 0, 0.0),
    (14, 30, 70, 50, 0, 0.0),
    (14, 35, 65, 50, 0, 0.0),
    # regime filter (SMA200 via ema): long above / short below
    (2, 15, 85, 50, 200, 0.0),
    (3, 20, 80, 50, 200, 0.0),
    (7, 30, 70, 50, 200, 0.0),
    (14, 35, 65, 50, 200, 0.0),
    # with stop-loss
    (3, 20, 80, 50, 0, 0.03),
    (2, 15, 85, 50, 0, 0.025),
]
for rsi_p, lo, hi, mid, ema_len, sl in GRID:
    tag = f"lsmr_r{rsi_p}_l{lo}_h{hi}_m{mid}_em{ema_len}_sl{int(sl*1000)}"
    CANDS.append((tag, ls_mr(rsi_p, lo, hi, mid, ema_len, sl)))


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
        name = f"_lssweep_{tag}"
        async with sm() as s:
            if await get_user_strategy_by_name(s, user_id=uid, name=name) is None:
                await create_user_strategy(
                    s, user_id=uid, org_id=oid, name=name, description="ls sweep",
                    nl_description="ls sweep", class_name=v.class_name, source_code=src,
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
        return (rr["tpw"] >= 3, rr["ret"] if rr["ret"] is not None else -1e9)
    results.sort(key=keyf, reverse=True)
    print(f"\n{'tag':38} {'tpw':>5} {'trd':>5} {'ret%':>8} {'pf':>5} {'win%':>5} {'dd%':>6} 3/wk")
    for rr in results:
        mark = "Y" if rr["tpw"] >= 3 else "."
        ret = f"{rr['ret']:.1f}" if rr["ret"] is not None else "n/a"
        pf = f"{float(rr['pf']):.2f}" if rr["pf"] else "n/a"
        wr = f"{float(rr['wr']):.0f}" if rr["wr"] else "n/a"
        dd = f"{float(rr['dd']):.1f}" if rr["dd"] else "n/a"
        print(f"{rr['tag']:38} {rr['tpw']:5.2f} {rr['n']:5d} {ret:>8} {pf:>5} {wr:>5} {dd:>6}   {mark}")

    winners = [rr for rr in results if rr["tpw"] >= 3 and (rr["ret"] or -1) > 0]
    print(f"\nPROFITABLE & >=3/wk: {len(winners)}")
    for w in sorted(winners, key=lambda x: x["ret"], reverse=True):
        print(f"  {w['tag']}  tpw={w['tpw']:.2f} ret={w['ret']:.1f}% pf={w['pf']} dd={w['dd']} bt={w['bt']}")


if __name__ == "__main__":
    asyncio.run(main())
