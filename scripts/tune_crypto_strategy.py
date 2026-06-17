"""Tighten the RSI band on the crypto strategy so it clears >=3 trades/week,
then re-backtest through the real engine + queue and verify from the DB.

Uses the platform's own validator, update_user_strategy, create_backtest and
the backtest_worker queue — same path the copilot's run_backtest tool uses.
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
from packages.strategy.validator import validate_strategy_source
from packages.data.user_strategies import update_user_strategy

STRAT_ID = "85a64263-e94a-461b-846e-ddac79452c0c"
USER_EMAIL = "aliasfar2006@gmail.com"
SYMBOL = "BTC-USDT@BINANCEUS"
WIN_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
WIN_END = datetime(2026, 1, 1, tzinfo=timezone.utc)
NEW_PARAMS = {"rsi_period": 14, "entry_threshold": 43.0, "exit_threshold": 48.0,
              "position_pct": 95.0}


async def main():
    sm = get_sessionmaker()
    async with sm() as s:
        user = (await s.execute(text(
            "SELECT id, org_id FROM users WHERE email=:e"),
            {"e": USER_EMAIL})).mappings().first()
        row = (await s.execute(text(
            "SELECT name, source_code FROM user_strategies WHERE id=:i"),
            {"i": STRAT_ID})).mappings().first()
        name, src = row["name"], row["source_code"]

        # Tighten the band defaults: entry 40 -> 43, exit 50 -> 48.
        new_src = (src
                   .replace("default=40.0", "default=43.0")
                   .replace("default=50.0", "default=48.0"))
        assert new_src != src, "default replacement did not apply"

        v = validate_strategy_source(new_src)
        if not v.ok:
            print("VALIDATION FAILED:", [e.as_dict() for e in v.errors][:3])
            return
        await update_user_strategy(
            s, strategy_id=STRAT_ID, user_id=user["id"],
            class_name=v.class_name, source_code=new_src,
            params_schema=v.params_schema)
        await s.commit()
        print(f"strategy updated: {name}  (band 43/48, rsi 14)")

        bt_id = await create_backtest(
            s, user_id=user["id"], org_id=user["org_id"], strategy_name=name,
            params_json=NEW_PARAMS, symbols=[SYMBOL], bar_resolution="1h",
            starting_cash=Decimal("25000"), fee_rate_bps=5, slippage_bps=3,
            window_start=WIN_START, window_end=WIN_END)
        await s.commit()
    r = redis.from_url("redis://redis:6379/0")
    await r.lpush(QUEUE_BACKTEST_JOBS, str(bt_id))
    print(f"backtest queued: {bt_id}")

    # Poll until terminal.
    status = "pending"
    for _ in range(60):
        await asyncio.sleep(4)
        async with sm() as s:
            status = (await s.execute(text(
                "SELECT status FROM backtests WHERE id=:b"), {"b": bt_id})).scalar()
        if status in ("completed", "failed"):
            break
    print(f"status: {status}")

    async with sm() as s:
        m = (await s.execute(text(
            "SELECT num_closed_trades, window_start, window_end "
            "FROM backtests WHERE id=:b"), {"b": bt_id})).mappings().first()
    n = m["num_closed_trades"] or 0
    weeks = (m["window_end"] - m["window_start"]).days / 7.0
    print(f"closed trades : {n}")
    print(f"weeks         : {weeks:.2f}")
    print(f"trades/week   : {n/weeks:.2f}")
    print(f">=3/week      : {'PASS' if n/weeks >= 3 else 'FAIL'}")
    print(f"backtest_id   : {bt_id}")


if __name__ == "__main__":
    asyncio.run(main())
