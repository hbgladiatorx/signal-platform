"""Restore the validated LINK long/short regime-reversion source that the studio
AI builder clobbered (it regenerated the strategy into a broken SMA50/RSI-cross
version with 0 trades, attached a graph, and renamed 1h->1H).

Fix in place: rewrite source_code to the validated version, NULL graph_json so
the builder can't auto-regenerate it, restore the lowercase name (matches its
backtest history), then queue a verification backtest to confirm it trades.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

import redis.asyncio as redis
from sqlalchemy import text

from packages.backtest.persistence import create_backtest
from packages.data.db import get_sessionmaker
from packages.data.messagebus import QUEUE_BACKTEST_JOBS
from packages.strategy.validator import validate_strategy_source
from deploy_crypto_winners import make_source

USER_EMAIL = "j@msn.com"
BROKEN_NAME = "LINK Regime Reversion 1H (Long/Short)"
GOOD_NAME = "LINK Regime Reversion 1h (Long/Short)"
SYMBOL = "LINK-USDT@BINANCEUS"

WINNER = {
    "name": GOOD_NAME, "symbol": SYMBOL, "tf": "1h",
    "rsi": 14, "lo": 43, "hi": 57, "le": 55, "se": 45, "sma": 200,
    "tp": 0.030, "sl": 0.06, "long_only": False,
}


async def main():
    src = make_source(WINNER)
    v = validate_strategy_source(src)
    if not v.ok:
        print("VALIDATION FAILED:", [e.as_dict() for e in v.errors][:2])
        return
    print("source valid, class:", v.class_name)

    sm = get_sessionmaker()
    async with sm() as s:
        u = (await s.execute(text("SELECT id, org_id FROM users WHERE email=:e"),
                             {"e": USER_EMAIL})).mappings().first()
        uid, oid = u["id"], u["org_id"]
        row = (await s.execute(text(
            "SELECT id FROM user_strategies WHERE user_id=:u AND name=:n"),
            {"u": uid, "n": BROKEN_NAME})).mappings().first()
        if row is None:
            print(f"no strategy named {BROKEN_NAME!r} under {USER_EMAIL}")
            return
        await s.execute(text(
            "UPDATE user_strategies SET name=:gn, source_code=:src, "
            "class_name=:cls, params_schema=CAST(:ps AS jsonb), graph_json=NULL, "
            "updated_at=now() WHERE id=:id"),
            {"gn": GOOD_NAME, "src": src, "cls": v.class_name,
             "ps": json.dumps(v.params_schema), "id": row["id"]})
        await s.commit()
        print(f"restored {row['id']} -> {GOOD_NAME} (graph cleared)")

    # Verify it trades again over full 2025.
    r = redis.from_url("redis://redis:6379/0")
    async with sm() as s:
        bt_id = await create_backtest(
            s, user_id=uid, org_id=oid, strategy_name=GOOD_NAME, params_json={},
            symbols=[SYMBOL], bar_resolution="1h", starting_cash=Decimal("25000"),
            fee_rate_bps=5, slippage_bps=3,
            window_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 1, 1, tzinfo=timezone.utc))
        await s.commit()
    await r.lpush(QUEUE_BACKTEST_JOBS, str(bt_id))

    for _ in range(120):
        await asyncio.sleep(4)
        async with sm() as s:
            m = (await s.execute(text(
                "SELECT status, num_closed_trades n, "
                "(analysis_json->'metrics'->>'total_return_pct') ret, "
                "(analysis_json->'metrics'->>'profit_factor') pf "
                "FROM backtests WHERE id=:b"), {"b": bt_id})).mappings().first()
        if m["status"] in ("completed", "failed"):
            break
    print(f"verify backtest {bt_id}: status={m['status']} trades={m['n']} "
          f"ret={m['ret']} pf={m['pf']}")


if __name__ == "__main__":
    asyncio.run(main())
