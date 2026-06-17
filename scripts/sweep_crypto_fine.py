"""Final fine-tune: land on >=3 trades/wk AND profitable, on BTC-USDT 1h 2025.

Frontier from sweep_crypto_win.py (RSI(14) MR + SMA200 regime filter):
  l40/h60 le55/se45 -> +22.6% pf1.77 but 1.75 tpw
  l42/h58 le50/se50 -> +2.1%  pf1.28 at 2.76 tpw  (just under 3/wk)
  r12 l42/h58       -> -11.7% pf1.08 at 3.53 tpw  (over 3/wk but negative)

Levers: widen entry to l43-44 (more trades) + asymmetric exit le55/se45 (let the
revert run, lifts per-trade edge) + optional take-profit (bank MR winners) and
protective stop (cap the 20% drawdown). Find the config that clears BOTH gates.
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

HEADER = '''"""FINE sweep candidate {name}."""
from __future__ import annotations
from pydantic import BaseModel
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class P(BaseModel):
    pass

'''


def ls_regime2(rsi_p, lo, hi, le, se, sma_len, tp, sl):
    """RSI MR + SMA regime filter, asymmetric exits, optional tp/sl (fractions)."""
    body = f'''
class {{cls}}(Strategy[P]):
    PARAMS_MODEL = P
    RSI_P = {rsi_p}
    LO = {lo}
    HI = {hi}
    LE = {le}
    SE = {se}
    SMA_LEN = {sma_len}
    TP = {tp}
    SL = {sl}

    def on_init(self) -> None:
        self.symbol = self.symbols[0]
        self.state["entry_px"] = None

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
                self.state["entry_px"] = px
            elif r > self.HI and px < sv:
                ctx.signal("regime_short", value=r, symbol=sym)
                ctx.submit_sell_market(sym, qty)
                self.state["entry_px"] = px
        elif pos > 0:
            ep = self.state["entry_px"]
            tp_hit = self.TP > 0 and ep is not None and px >= ep * (1 + self.TP)
            sl_hit = self.SL > 0 and ep is not None and px <= ep * (1 - self.SL)
            if r > self.LE or tp_hit or sl_hit:
                ctx.signal("regime_long_exit", value=r, symbol=sym)
                ctx.submit_sell_market(sym, pos)
                self.state["entry_px"] = None
        else:
            ep = self.state["entry_px"]
            tp_hit = self.TP > 0 and ep is not None and px <= ep * (1 - self.TP)
            sl_hit = self.SL > 0 and ep is not None and px >= ep * (1 + self.SL)
            if r < self.SE or tp_hit or sl_hit:
                ctx.signal("regime_short_exit", value=r, symbol=sym)
                ctx.submit_buy_market(sym, -pos)
                self.state["entry_px"] = None
'''
    return body


CANDS = []
# (rsi_p, lo, hi, le, se, sma_len, tp, sl)
GRID = [
    (14, 43, 57, 50, 50, 200, 0.0, 0.0),
    (14, 44, 56, 50, 50, 200, 0.0, 0.0),
    (14, 43, 57, 55, 45, 200, 0.0, 0.0),
    (14, 44, 56, 55, 45, 200, 0.0, 0.0),
    (14, 42, 58, 55, 45, 200, 0.0, 0.0),
    (14, 42, 58, 52, 48, 200, 0.0, 0.0),
    (14, 43, 57, 52, 48, 200, 0.0, 0.0),
    (14, 45, 55, 55, 45, 200, 0.0, 0.0),
    # take-profit to bank winners at wider bands
    (14, 44, 56, 50, 50, 200, 0.03, 0.0),
    (14, 45, 55, 55, 45, 200, 0.03, 0.0),
    (14, 44, 56, 55, 45, 200, 0.025, 0.06),
    # protective stop to cap drawdown on the target band
    (14, 43, 57, 55, 45, 200, 0.0, 0.05),
    (14, 44, 56, 55, 45, 200, 0.0, 0.05),
    # regime MA variations around the best band
    (14, 43, 57, 55, 45, 250, 0.0, 0.0),
    (14, 44, 56, 55, 45, 250, 0.0, 0.0),
    (14, 43, 57, 55, 45, 150, 0.0, 0.0),
]
for rsi_p, lo, hi, le, se, sma_len, tp, sl in GRID:
    tag = f"fin_r{rsi_p}_l{lo}_h{hi}_le{le}_se{se}_s{sma_len}_tp{int(tp*1000)}_sl{int(sl*1000)}"
    CANDS.append((tag, ls_regime2(rsi_p, lo, hi, le, se, sma_len, tp, sl)))


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
        name = f"_finsweep_{tag}"
        async with sm() as s:
            if await get_user_strategy_by_name(s, user_id=uid, name=name) is None:
                await create_user_strategy(
                    s, user_id=uid, org_id=oid, name=name, description="fine sweep",
                    nl_description="fine sweep", class_name=v.class_name, source_code=src,
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
        return (meets, float(rr["pf"]) if rr["pf"] else -1e9)
    results.sort(key=keyf, reverse=True)
    print(f"\n{'cfg':44} {'tpw':>5} {'trd':>4} {'ret%':>7} {'pf':>5} {'win':>4} {'dd':>5} {'shrp':>5} 3wk")
    for rr in results:
        mark = "Y" if (rr["tpw"] >= 3 and (rr["ret"] or -1) > 0) else ("~" if rr["tpw"] >= 3 else ".")
        ret = f"{rr['ret']:.1f}" if rr["ret"] is not None else "n/a"
        pf = f"{float(rr['pf']):.2f}" if rr["pf"] else "n/a"
        wr = f"{float(rr['wr']):.0f}" if rr["wr"] else "n/a"
        dd = f"{float(rr['dd']):.0f}" if rr["dd"] else "n/a"
        sh = f"{float(rr['sh']):.2f}" if rr["sh"] else "n/a"
        print(f"{rr['tag'][4:]:44} {rr['tpw']:5.2f} {rr['n']:4d} {ret:>7} {pf:>5} {wr:>4} {dd:>5} {sh:>5}  {mark}")

    winners = [rr for rr in results if rr["tpw"] >= 3 and (rr["ret"] or -1) > 0]
    print(f"\nPROFITABLE & >=3/wk: {len(winners)}")
    for w in sorted(winners, key=lambda x: float(x["pf"] or 0), reverse=True):
        print(f"  WINNER {w['tag']}  tpw={w['tpw']:.2f} ret={w['ret']:.1f}% pf={w['pf']} dd={w['dd']}% sharpe={w['sh']} bt={w['bt']}")


if __name__ == "__main__":
    asyncio.run(main())
