"""Local end-to-end probe for the skip-forward-test lifecycle transition.

Exercises the REAL SQL of set_strategy_lifecycle_milestone + compute_strategy_state
against the real schema, then ROLLS BACK — proves the transition end-to-end while
mutating nothing in production. Read-then-rollback; never commits.

Run inside an app-api container on signal_net.
"""
import asyncio
import sys
from uuid import UUID

from sqlalchemy import text

from packages.data.db import get_sessionmaker
from packages.copilot.state import compute_strategy_state
from packages.data.user_strategies import (
    get_user_strategy,
    set_strategy_lifecycle_milestone,
)

USER_ID = UUID("a93b45bb-d09e-48f3-aae2-0c4c6360b8d6")  # flow-audit
STRAT_NAME = sys.argv[1] if len(sys.argv) > 1 else "SPY RSI Oversold Reversal"


def _show(tag, s):
    g = s["gates_passed"]
    print(f"  [{tag}] stage={s['stage']!r:14} forward_test={s['forward_test']!r:10} "
          f"oos_passed={g['oos_passed']} forward_started={g['forward_started']} "
          f"forward_test_skipped={g['forward_test_skipped']} promoted={g['promoted']}")


async def main():
    Session = get_sessionmaker()
    async with Session() as session:
        # locate the strategy row
        r = await session.execute(
            text("SELECT id FROM user_strategies WHERE user_id=:u AND name=:n"),
            {"u": USER_ID, "n": STRAT_NAME},
        )
        row = r.first()
        if not row:
            print(f"NO SUCH STRATEGY: {STRAT_NAME!r} for flow-audit"); return
        sid = row[0]
        print(f"Strategy: {STRAT_NAME!r}  id={sid}")

        # Within this uncommitted tx only: clear the milestone columns so we can
        # demonstrate the real not-skipped -> skipped transition. Rolled back below,
        # so the persisted row is never changed.
        await session.execute(
            text("UPDATE user_strategies SET forward_test_skipped_at=NULL, promoted_at=NULL "
                 "WHERE id=:id AND user_id=:u"),
            {"id": sid, "u": USER_ID},
        )
        srow = await get_user_strategy(session, strategy_id=sid, user_id=USER_ID)
        before = await compute_strategy_state(session, user_id=USER_ID, strategy_row=srow)
        _show("BEFORE", before)

        if not before["gates_passed"]["oos_passed"]:
            print("  !! not oos_passed — the endpoint would 422 here (block-before-OOS). Stopping.")
            await session.rollback(); return

        # THE TRANSITION (same call the endpoint makes)
        await set_strategy_lifecycle_milestone(
            session, strategy_id=sid, user_id=USER_ID,
            forward_skipped=True, promoted=True,
        )
        # re-read within the same uncommitted tx
        srow2 = await get_user_strategy(session, strategy_id=sid, user_id=USER_ID)
        after = await compute_strategy_state(session, user_id=USER_ID, strategy_row=srow2)
        _show("AFTER ", after)

        # assertions: skip recorded DISTINCT from pass, advanced to deployable
        g = after["gates_passed"]
        ok = (after["forward_test"] == "skipped"
              and g["forward_test_skipped"] is True
              and g["forward_started"] is False          # never read as passed
              and after["stage"] == "deployable")
        print("  RESULT:", "PASS ✓ (skipped, forward_started stays False, stage=deployable)"
              if ok else "FAIL ✗")

        # leave production exactly as found
        await session.rollback()
        print("  rolled back — production state untouched.")

        # confirm rollback actually reverted
        srow3 = await get_user_strategy(session, strategy_id=sid, user_id=USER_ID)
        confirm = await compute_strategy_state(session, user_id=USER_ID, strategy_row=srow3)
        _show("REVERTED", confirm)


asyncio.run(main())
