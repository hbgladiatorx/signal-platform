"""Drive the Bayn Copilot to build a CRYPTO strategy that trades >= 3x/week.

Only crypto with bar history is BTC-USDT@BINANCEUS, 1h, 2025-01-01..2026-01-01.
Builds a tight-band RSI mean-reversion (frequent in/out), backtests over the
data window, then measures closed trades per week straight from the DB so the
>=3/week constraint is verified objectively, not from the LLM's prose.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from packages.copilot.agent import run_copilot_turn
from packages.data.db import get_sessionmaker
from services.api.deps import CurrentUserRecord
from services.api.routers.strategies import get_strategy_registry

USER_EMAIL = "aliasfar2006@gmail.com"
WIN_START = "2025-01-01"
WIN_END = "2026-01-01"

BUILD_MSG = (
    "Build a CRYPTO mean-reversion strategy on BTC-USDT on Binance.US "
    "(symbol BTC-USDT@BINANCEUS), using 1-hour bars. Go long when the "
    "14-period RSI drops below 40, and close the long when the 14-period RSI "
    "rises back above 50. Long only, no stop-loss. It should trade frequently "
    "— several times per week."
)
BACKTEST_MSG = (
    f"Backtest it on BTC-USDT using 1-hour bars over the window "
    f"{WIN_START} to {WIN_END}."
)


def show(label, r):
    print(f"\n{'='*70}\n[{label}] ok={r.ok} strategy_id={r.strategy_id} "
          f"tok={r.input_tokens}/{r.output_tokens}")
    if r.error:
        print("ERROR:", r.error)
    print(r.reply[:1400])
    for t in (r.tool_trace or []):
        out = t.get("output") or t.get("result") or {}
        brief = {k: out[k] for k in ("ok", "status", "strategy_id", "backtest_id",
                 "stage", "note") if isinstance(out, dict) and k in out}
        print(f"   -> {t.get('name')}: {brief}")


async def main():
    sm = get_sessionmaker()
    async with sm() as s:
        row = (await s.execute(
            text("SELECT id, org_id, email, role FROM users WHERE email=:e"),
            {"e": USER_EMAIL})).mappings().first()
        if not row:
            print("no user"); sys.exit(1)
        user = CurrentUserRecord(**dict(row))
    registry = get_strategy_registry()
    convo, sid = [], None

    async def turn(msg, label):
        nonlocal sid, convo
        convo.append({"role": "user", "content": msg})
        async with sm() as s:
            r = await run_copilot_turn(session=s, user=user, registry=registry,
                                       messages=convo, strategy_id=sid)
        show(label, r)
        convo.append({"role": "assistant", "content": r.reply})
        if r.strategy_id:
            sid = r.strategy_id
        # surface backtest_id if present
        bt = None
        for t in (r.tool_trace or []):
            out = t.get("output") or {}
            if isinstance(out, dict) and out.get("backtest_id"):
                bt = out["backtest_id"]
        return bt

    await turn(BUILD_MSG, "BUILD")
    bt_id = await turn(BACKTEST_MSG, "BACKTEST")

    # ---- objective verification straight from the DB ----
    print(f"\n{'='*70}\nVERIFICATION  strategy_id={sid}")
    async with sm() as s:
        if not bt_id:
            bt = (await s.execute(text(
                "SELECT id FROM backtests WHERE strategy_name=(SELECT name FROM "
                "user_strategies WHERE id=:sid) ORDER BY created_at DESC LIMIT 1"),
                {"sid": sid})).scalar()
            bt_id = str(bt) if bt else None
        if not bt_id:
            print("no backtest found"); return
        meta = (await s.execute(text(
            "SELECT status, num_closed_trades, symbols, bar_resolution, "
            "window_start, window_end FROM backtests WHERE id=:b"),
            {"b": bt_id})).mappings().first()
        rng = (await s.execute(text(
            "SELECT min(entry_ts) f, max(exit_ts) l, count(*) n "
            "FROM backtest_trades WHERE backtest_id=:b"), {"b": bt_id})).mappings().first()
    n = meta["num_closed_trades"] or 0
    ws, we = meta["window_start"], meta["window_end"]
    weeks = (we - ws).days / 7.0 if ws and we else 0
    per_week = n / weeks if weeks else 0
    print(f"backtest_id     : {bt_id}")
    print(f"status          : {meta['status']}")
    print(f"symbols         : {meta['symbols']}")
    print(f"bar_resolution  : {meta['bar_resolution']}")
    print(f"window          : {ws} -> {we}  ({weeks:.1f} weeks)")
    print(f"closed trades   : {n}")
    print(f"trades / week   : {per_week:.2f}")
    print(f"trade span      : {rng['f']} -> {rng['l']} (n={rng['n']})")
    print(f"CONSTRAINT >=3/wk: {'PASS' if per_week >= 3 else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
