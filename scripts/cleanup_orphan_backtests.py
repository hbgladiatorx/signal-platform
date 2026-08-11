"""Delete orphaned backtest runs — runs whose strategy no longer exists.

A backtest is "orphaned" when its strategy_name matches neither an ACTIVE
user_strategy for its owner nor a built-in strategy. These pile up when a user
deletes a strategy: the strategy row is soft-deleted but its backtest runs stay,
so they still appear on the dashboard's per-run "Recent backtests" list yet are
absent from the per-strategy "View all" page (which lists only active
strategies). Built-in strategies (e.g. SMACrossover) are KEPT.

Dry-run by default — prints what WOULD be deleted. Pass --apply to delete
(cascades to each run's trades + equity points via ON DELETE CASCADE).

  # dry-run, everyone
  python -m scripts.cleanup_orphan_backtests
  # dry-run, one owner
  python -m scripts.cleanup_orphan_backtests --user-email hb_gladiator@outlook.com
  # actually delete, one owner
  python -m scripts.cleanup_orphan_backtests --user-email hb_gladiator@outlook.com --apply

Run it inside the api container, which has the DB env + deps:
  docker compose exec api python -m scripts.cleanup_orphan_backtests --user-email … --apply
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Iterable

from sqlalchemy import text

from packages.data.db import get_sessionmaker
from packages.strategy.registry import discover_strategies


def orphan_ids(
    backtests: Iterable[dict[str, Any]],
    active_names: Iterable[str],
    builtin_names: Iterable[str],
) -> list[str]:
    """Backtest ids whose strategy_name is neither an active user-strategy nor a
    built-in. Pure (no DB) so the rule is unit-testable."""
    keep = {(n or "").strip() for n in active_names} | {
        (n or "").strip() for n in builtin_names
    }
    return [
        str(b["id"])
        for b in backtests
        if (b.get("strategy_name") or "").strip() not in keep
    ]


async def _target_user_ids(session, email: str | None) -> list[str]:
    if email:
        row = (
            await session.execute(
                text("SELECT id FROM users WHERE lower(email) = lower(:e)"),
                {"e": email},
            )
        ).first()
        if row is None:
            raise SystemExit(f"No user found with email {email!r}.")
        return [str(row[0])]
    rows = (
        await session.execute(text("SELECT DISTINCT user_id FROM backtests"))
    ).fetchall()
    return [str(r[0]) for r in rows]


async def main() -> None:
    ap = argparse.ArgumentParser(description="Delete orphaned backtest runs.")
    ap.add_argument("--user-email", default=None, help="Scope to one owner (default: all).")
    ap.add_argument("--apply", action="store_true", help="Actually delete (default: dry-run).")
    args = ap.parse_args()

    builtin_names = set(discover_strategies().keys())
    Session = get_sessionmaker()
    total_orphans = 0

    async with Session() as session:
        user_ids = await _target_user_ids(session, args.user_email)
        for uid in user_ids:
            active = [
                r[0]
                for r in (
                    await session.execute(
                        text(
                            "SELECT name FROM user_strategies "
                            "WHERE user_id = :uid AND is_active = TRUE"
                        ),
                        {"uid": uid},
                    )
                ).fetchall()
            ]
            bts = [
                dict(r._mapping)
                for r in (
                    await session.execute(
                        text(
                            "SELECT id, strategy_name, symbols, created_at, "
                            "num_closed_trades, total_return_pct "
                            "FROM backtests WHERE user_id = :uid "
                            "ORDER BY created_at DESC"
                        ),
                        {"uid": uid},
                    )
                ).fetchall()
            ]
            ids = orphan_ids(bts, active, builtin_names)
            if not ids:
                continue
            total_orphans += len(ids)

            # Group for a readable report.
            by_name: dict[str, int] = {}
            for b in bts:
                if str(b["id"]) in set(ids):
                    by_name[b.get("strategy_name") or "(unnamed)"] = (
                        by_name.get(b.get("strategy_name") or "(unnamed)", 0) + 1
                    )
            verb = "Deleting" if args.apply else "Would delete"
            print(f"\nuser {uid}: {verb} {len(ids)} orphaned run(s):")
            for name, n in sorted(by_name.items(), key=lambda kv: -kv[1]):
                print(f"    {n:>5}  {name}")

            if args.apply:
                await session.execute(
                    text(
                        "DELETE FROM backtests WHERE id = ANY(:ids) AND user_id = :uid"
                    ),
                    {"ids": ids, "uid": uid},
                )
                await session.commit()

    if total_orphans == 0:
        print("No orphaned backtests found. Nothing to clean up.")
    elif not args.apply:
        print(f"\nDry-run: {total_orphans} orphaned run(s) would be deleted. "
              f"Re-run with --apply to delete them.")
    else:
        print(f"\nDone: deleted {total_orphans} orphaned run(s).")


if __name__ == "__main__":
    asyncio.run(main())
