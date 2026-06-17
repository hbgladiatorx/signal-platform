"""Screen the proven regime-reversion edge across multiple symbols + timeframes.

The deployed winner ("BTC Regime Reversion 1h") = RSI(14) MR + SMA200 regime
filter, asymmetric exits (long->RSI55 / short->RSI45) + 1.25% take-profit, on
BTC-USDT 1h 2025 (+12.3%, pf1.38). This script applies the SAME structure to
other liquid pairs at 1h, and to BTC/ETH/SOL at 15m (with a longer SMA so the
regime window stays ~comparable to the 1h winner's 200h), then reports which
combos are profitable so we can deploy the winners.
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
WIN_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
WIN_END = datetime(2026, 1, 1, tzinfo=timezone.utc)
WEEKS = (WIN_END - WIN_START).days / 7.0
PCT = 90.0

HEADER = '''"""SCREEN candidate {name}."""
from __future__ import annotations
from pydantic import BaseModel
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class P(BaseModel):
    pass

'''


def regime_body(rsi_p, lo, hi, le, se, sma_len, tp):
    """RSI MR + SMA regime filter, asymmetric exits, optional take-profit."""
    return f'''
class {{cls}}(Strategy[P]):
    PARAMS_MODEL = P
    RSI_P = {rsi_p}
    LO = {lo}
    HI = {hi}
    LE = {le}
    SE = {se}
    SMA_LEN = {sma_len}
    TP = {tp}

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
            if r > self.LE or tp_hit:
                ctx.signal("regime_long_exit", value=r, symbol=sym)
                ctx.submit_sell_market(sym, pos)
                self.state["entry_px"] = None
        else:
            ep = self.state["entry_px"]
            tp_hit = self.TP > 0 and ep is not None and px <= ep * (1 - self.TP)
            if r < self.SE or tp_hit:
                ctx.signal("regime_short_exit", value=r, symbol=sym)
                ctx.submit_buy_market(sym, -pos)
                self.state["entry_px"] = None
'''


# (label, symbol, timeframe, rsi_p, lo, hi, le, se, sma_len, tp)
# 1h: proven band (sma200 = 200h regime). 15m: sma800 = 200h regime, tighter tp.
GRID = [
    # --- 1h across liquid pairs (proven 1h params) ---
    ("ETH_1h",  "ETH-USDT@BINANCEUS",  "1h", 14, 43, 57, 55, 45, 200, 0.0125),
    ("SOL_1h",  "SOL-USDT@BINANCEUS",  "1h", 14, 43, 57, 55, 45, 200, 0.0125),
    ("BNB_1h",  "BNB-USDT@BINANCEUS",  "1h", 14, 43, 57, 55, 45, 200, 0.0125),
    ("LINK_1h", "LINK-USDT@BINANCEUS", "1h", 14, 43, 57, 55, 45, 200, 0.0125),
    ("AVAX_1h", "AVAX-USDT@BINANCEUS", "1h", 14, 43, 57, 55, 45, 200, 0.0125),
    ("XRP_1h",  "XRP-USDT@BINANCEUS",  "1h", 14, 43, 57, 55, 45, 200, 0.0125),
    ("DOGE_1h", "DOGE-USDT@BINANCEUS", "1h", 14, 43, 57, 55, 45, 200, 0.0125),
    ("ADA_1h",  "ADA-USDT@BINANCEUS",  "1h", 14, 43, 57, 55, 45, 200, 0.0125),
    ("LTC_1h",  "LTC-USDT@BINANCEUS",  "1h", 14, 43, 57, 55, 45, 200, 0.0125),
    # --- 15m higher-frequency (sma800 ~ 200h regime, tp 0.8%) ---
    ("BTC_15m", "BTC-USDT@BINANCEUS",  "15m", 14, 43, 57, 55, 45, 800, 0.008),
    ("ETH_15m", "ETH-USDT@BINANCEUS",  "15m", 14, 43, 57, 55, 45, 800, 0.008),
    ("SOL_15m", "SOL-USDT@BINANCEUS",  "15m", 14, 43, 57, 55, 45, 800, 0.008),
    # 15m BTC variant: shorter regime + a touch wider entry (more trades)
    ("BTC_15m_s400", "BTC-USDT@BINANCEUS", "15m", 14, 44, 56, 55, 45, 400, 0.008),
    ("ETH_15m_s400", "ETH-USDT@BINANCEUS", "15m", 14, 44, 56, 55, 45, 400, 0.008),
]


async def main():
    sm = get_sessionmaker()
    async with sm() as s:
        u = (await s.execute(text("SELECT id, org_id FROM users WHERE email=:e"),
                             {"e": USER_EMAIL})).mappings().first()
        uid, oid = u["id"], u["org_id"]

    jobs = []
    r = redis.from_url("redis://redis:6379/0")
    for label, sym, tf, rsi_p, lo, hi, le, se, sma_len, tp in GRID:
        cls = "S_" + label.replace(".", "_")
        src = HEADER.format(name=label) + regime_body(rsi_p, lo, hi, le, se, sma_len, tp).format(cls=cls)
        v = validate_strategy_source(src)
        if not v.ok:
            print(f"SKIP {label}: {[e.as_dict() for e in v.errors][:1]}")
            continue
        name = f"_multiscreen_{label}"
        async with sm() as s:
            if await get_user_strategy_by_name(s, user_id=uid, name=name) is None:
                await create_user_strategy(
                    s, user_id=uid, org_id=oid, name=name, description="multi screen",
                    nl_description="multi screen", class_name=v.class_name, source_code=src,
                    params_schema=v.params_schema, asset_class="crypto")
                await s.commit()
            bt_id = await create_backtest(
                s, user_id=uid, org_id=oid, strategy_name=name, params_json={},
                symbols=[sym], bar_resolution=tf, starting_cash=Decimal("25000"),
                fee_rate_bps=5, slippage_bps=3, window_start=WIN_START, window_end=WIN_END)
            await s.commit()
        await r.lpush(QUEUE_BACKTEST_JOBS, str(bt_id))
        jobs.append((label, sym, tf, str(bt_id)))
    print(f"queued {len(jobs)} backtests")

    pending = {bt for _, _, _, bt in jobs}
    for _ in range(240):
        await asyncio.sleep(4)
        async with sm() as s:
            rows = (await s.execute(text(
                "SELECT id::text id, status FROM backtests WHERE id = ANY(:ids)"),
                {"ids": list(pending)})).mappings().all()
        pending -= {row["id"] for row in rows if row["status"] in ("completed", "failed")}
        if not pending:
            break
    print(f"unfinished: {len(pending)}")

    results = []
    async with sm() as s:
        for label, sym, tf, bt in jobs:
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
                "label": label, "sym": sym, "tf": tf, "status": m["status"],
                "n": n, "tpw": n / WEEKS,
                "ret": float(m["ret"]) if m["ret"] is not None else None,
                "pf": float(m["pf"]) if m["pf"] else None,
                "wr": float(m["wr"]) if m["wr"] else None,
                "dd": float(m["dd"]) if m["dd"] else None,
                "sh": float(m["sh"]) if m["sh"] else None, "bt": bt})

    def good(rr):
        return (rr["ret"] or -1) > 0 and (rr["pf"] or 0) >= 1.1 and rr["n"] >= 20
    results.sort(key=lambda rr: (good(rr), rr["pf"] or -1), reverse=True)
    print(f"\n{'label':16} {'tf':>4} {'tpw':>5} {'trd':>4} {'ret%':>7} {'pf':>5} {'win':>4} {'dd':>5} {'shrp':>5} ok")
    for rr in results:
        ret = f"{rr['ret']:.1f}" if rr["ret"] is not None else "n/a"
        pf = f"{rr['pf']:.2f}" if rr["pf"] else "n/a"
        wr = f"{rr['wr']:.0f}" if rr["wr"] else "n/a"
        dd = f"{rr['dd']:.0f}" if rr["dd"] else "n/a"
        sh = f"{rr['sh']:.2f}" if rr["sh"] else "n/a"
        print(f"{rr['label']:16} {rr['tf']:>4} {rr['tpw']:5.2f} {rr['n']:4d} {ret:>7} "
              f"{pf:>5} {wr:>4} {dd:>5} {sh:>5}  {'Y' if good(rr) else '.'}  bt={rr['bt']}")

    winners = [rr for rr in results if good(rr)]
    print(f"\nPROFITABLE (ret>0, pf>=1.1, >=20 trd): {len(winners)}")
    for w in winners:
        print(f"  WIN {w['label']:16} {w['sym']:22} {w['tf']:>4} ret={w['ret']:.1f}% "
              f"pf={w['pf']:.2f} tpw={w['tpw']:.2f} dd={w['dd']:.0f}% sharpe={w['sh']:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
