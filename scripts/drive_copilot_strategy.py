"""Drive the Bayn Copilot end-to-end to produce one working strategy.

Runs the real platform agent loop (build -> backtest -> analysis) as a given
user, exactly like POST /copilot/chat does, but without HTTP/JWT.
"""
from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import text

from packages.copilot.agent import run_copilot_turn
from packages.data.db import get_sessionmaker
from services.api.deps import CurrentUserRecord
from services.api.routers.strategies import get_strategy_registry

USER_EMAIL = "aliasfar2006@gmail.com"


def show(turn_label: str, result) -> None:
    print(f"\n{'='*70}\n[{turn_label}]  ok={result.ok}  strategy_id={result.strategy_id}")
    print(f"tokens in/out={result.input_tokens}/{result.output_tokens}")
    if result.error:
        print("ERROR:", result.error)
    print("--- reply ---")
    print(result.reply)
    if result.tool_trace:
        print("--- tool_trace ---")
        for t in result.tool_trace:
            name = t.get("name")
            out = t.get("output") or t.get("result") or {}
            if isinstance(out, dict):
                brief = {k: out[k] for k in ("ok", "status", "strategy_id", "backtest_id", "stage") if k in out}
            else:
                brief = str(out)[:200]
            print(f"  -> {name}: {brief}")
    if result.state:
        print("--- state ---")
        print("  stage:", result.state.get("stage"))


async def main() -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        row = (
            await session.execute(
                text("SELECT id, org_id, email, role FROM users WHERE email = :e"),
                {"e": USER_EMAIL},
            )
        ).mappings().first()
        if not row:
            print("user not found:", USER_EMAIL)
            sys.exit(1)
        user = CurrentUserRecord(**dict(row))
        print("driving copilot as", user.email, user.id)

    registry = get_strategy_registry()
    convo: list[dict] = []
    sid = None

    async def turn(text_msg: str, label: str):
        nonlocal sid, convo
        convo.append({"role": "user", "content": text_msg})
        sm2 = get_sessionmaker()
        async with sm2() as session:
            result = await run_copilot_turn(
                session=session,
                user=user,
                registry=registry,
                messages=convo,
                strategy_id=sid,
            )
        show(label, result)
        # Append the assistant reply so the conversation carries forward.
        convo.append({"role": "assistant", "content": result.reply})
        if result.strategy_id:
            sid = result.strategy_id
        return result

    await turn(
        "Build me a simple SMA crossover strategy on AAPL: go long when the "
        "20-day simple moving average crosses above the 50-day SMA, and exit "
        "when it crosses back below. US stocks.",
        "BUILD",
    )
    await turn(
        "Backtest it on AAPL over the last 2 years with daily bars.",
        "BACKTEST",
    )
    await turn(
        "Show me the backtest analysis — total return, number of trades, "
        "win rate and max drawdown.",
        "ANALYSIS",
    )

    print("\nFINAL strategy_id:", sid)


if __name__ == "__main__":
    asyncio.run(main())
