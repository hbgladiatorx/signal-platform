"""Strategy lifecycle state — the single source of truth the copilot reasons over.

The pipeline is six ordered stages:

    draft -> backtested -> oos_passed -> forward -> deployable -> bayn_eligible

The first four are DERIVED from real artifacts every time we read state, so they
can never drift from reality:
  * backtested  — at least one completed backtest exists for the strategy
  * oos_passed  — at least one completed walk-forward clears the OOS gate
  * forward     — at least one paper session exists for the strategy

The last two are gated, confirmation-only transitions stored on user_strategies:
  * deployable     — promoted_at is set (promote_strategy)
  * bayn_eligible  — deployed_live_at is set (deploy_strategy mode=live)

`compute_strategy_state` returns the same {stage, latest_backtest_id, trade_count,
sharpe, gates_passed, ...} shape the chat chips, the pipeline stepper, and the
agent's "what's next" line all read — one map, three consumers.

Backtests / walk-forwards / paper sessions are linked to a strategy by
strategy_name (their FK of record), scoped to the owning user.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Ordered stages. Index = how far along the pipeline.
STAGES: list[str] = [
    "draft",
    "backtested",
    "oos_passed",
    "forward",
    "deployable",
    "bayn_eligible",
]

# The minimum number of closed trades for a backtest to be statistically
# trustworthy. Below this, the copilot must say so before quoting ratios.
MIN_TRUSTWORTHY_TRADES = 30


def oos_gate_passed(wf: dict[str, Any]) -> bool:
    """Did this completed walk-forward hold up out of sample?

    Conservative gate: the strategy must be net positive on the held-out test
    windows (avg_test_sharpe > 0). overfit_drop (train->test degradation) is
    surfaced for the verdict but not hard-gated — a positive but degraded
    out-of-sample sharpe still counts as having survived OOS.
    """
    if wf.get("status") != "completed":
        return False
    ats = wf.get("avg_test_sharpe")
    return ats is not None and float(ats) > 0.0


def _f(v: Any) -> Optional[float]:
    return float(v) if v is not None else None


async def _latest_backtest(
    session: AsyncSession, user_id: UUID, strategy_name: str
) -> Optional[dict[str, Any]]:
    row = await session.execute(
        text(
            """
            SELECT id, status, num_closed_trades, sharpe_ratio,
                   total_return_pct, max_drawdown_pct, created_at
            FROM backtests
            WHERE user_id = :uid AND strategy_name = :name
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"uid": user_id, "name": strategy_name},
    )
    m = row.mappings().first()
    return dict(m) if m else None


async def _has_completed_backtest(
    session: AsyncSession, user_id: UUID, strategy_name: str
) -> bool:
    row = await session.execute(
        text(
            """
            SELECT 1 FROM backtests
            WHERE user_id = :uid AND strategy_name = :name AND status = 'completed'
            LIMIT 1
            """
        ),
        {"uid": user_id, "name": strategy_name},
    )
    return row.first() is not None


async def _latest_walkforward(
    session: AsyncSession, user_id: UUID, strategy_name: str
) -> Optional[dict[str, Any]]:
    row = await session.execute(
        text(
            """
            SELECT id, status, avg_test_sharpe, avg_test_return_pct,
                   overfit_drop, created_at
            FROM walkforwards
            WHERE user_id = :uid AND strategy_name = :name
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"uid": user_id, "name": strategy_name},
    )
    m = row.mappings().first()
    return dict(m) if m else None


async def _any_oos_passed(
    session: AsyncSession, user_id: UUID, strategy_name: str
) -> bool:
    """True if ANY completed walk-forward for this strategy clears the OOS gate."""
    rows = await session.execute(
        text(
            """
            SELECT status, avg_test_sharpe
            FROM walkforwards
            WHERE user_id = :uid AND strategy_name = :name AND status = 'completed'
            """
        ),
        {"uid": user_id, "name": strategy_name},
    )
    return any(oos_gate_passed(dict(r)) for r in rows.mappings())


async def _latest_paper_session(
    session: AsyncSession, user_id: UUID, strategy_name: str
) -> Optional[dict[str, Any]]:
    row = await session.execute(
        text(
            """
            SELECT id, status, mode, created_at
            FROM paper_sessions
            WHERE user_id = :uid AND strategy_name = :name
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"uid": user_id, "name": strategy_name},
    )
    m = row.mappings().first()
    return dict(m) if m else None


def _derive_stage(
    *,
    has_backtest: bool,
    oos_passed: bool,
    has_forward: bool,
    promoted: bool,
    deployed_live: bool,
) -> str:
    """Highest stage whose predicate is satisfied. Stored milestones (promoted /
    deployed_live) imply every earlier stage was reached."""
    if deployed_live:
        return "bayn_eligible"
    if promoted:
        return "deployable"
    if has_forward:
        return "forward"
    if oos_passed:
        return "oos_passed"
    if has_backtest:
        return "backtested"
    return "draft"


async def compute_strategy_state(
    session: AsyncSession,
    *,
    user_id: UUID,
    strategy_row: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate everything the copilot needs to decide the next action.

    `strategy_row` is a get_user_strategy() row (includes the milestone columns).
    """
    name = strategy_row["name"]

    latest_bt = await _latest_backtest(session, user_id, name)
    has_bt = await _has_completed_backtest(session, user_id, name)
    latest_wf = await _latest_walkforward(session, user_id, name)
    oos_passed = await _any_oos_passed(session, user_id, name)
    latest_paper = await _latest_paper_session(session, user_id, name)

    promoted = strategy_row.get("promoted_at") is not None
    deployed_live = strategy_row.get("deployed_live_at") is not None

    stage = _derive_stage(
        has_backtest=has_bt,
        oos_passed=oos_passed,
        has_forward=latest_paper is not None,
        promoted=promoted,
        deployed_live=deployed_live,
    )

    trade_count = latest_bt.get("num_closed_trades") if latest_bt else None
    sharpe = _f(latest_bt.get("sharpe_ratio")) if latest_bt else None
    total_return = _f(latest_bt.get("total_return_pct")) if latest_bt else None

    gates_passed = {
        "backtest_completed": has_bt,
        "enough_trades": bool(trade_count is not None and trade_count >= MIN_TRUSTWORTHY_TRADES),
        "profitable_backtest": bool(total_return is not None and total_return > 0),
        "oos_passed": oos_passed,
        "forward_started": latest_paper is not None,
        "promoted": promoted,
        "deployed_live": deployed_live,
        "submitted_to_bayn": strategy_row.get("submitted_to_bayn_at") is not None,
    }

    return {
        "strategy_id": str(strategy_row["id"]),
        "name": name,
        "asset_class": strategy_row.get("asset_class"),
        "stage": stage,
        "stage_index": STAGES.index(stage),
        # Latest backtest summary
        "latest_backtest_id": str(latest_bt["id"]) if latest_bt else None,
        "latest_backtest_status": latest_bt.get("status") if latest_bt else None,
        "trade_count": trade_count,
        "sharpe": sharpe,
        "total_return_pct": total_return,
        # Latest OOS / walk-forward
        "latest_oos_id": str(latest_wf["id"]) if latest_wf else None,
        "latest_oos_status": latest_wf.get("status") if latest_wf else None,
        "avg_test_sharpe": _f(latest_wf.get("avg_test_sharpe")) if latest_wf else None,
        # Latest forward / paper session
        "latest_forward_session_id": str(latest_paper["id"]) if latest_paper else None,
        "latest_forward_status": latest_paper.get("status") if latest_paper else None,
        "last_deploy_mode": strategy_row.get("last_deploy_mode"),
        "gates_passed": gates_passed,
        "next_action": next_action_for_stage(stage, gates_passed),
    }


# ============================================================
# stage -> call-to-action. One map drives the chat chips, the pipeline
# stepper button, and the agent's "what's next" line.
# ============================================================
def next_action_for_stage(stage: str, gates: dict[str, bool]) -> dict[str, str]:
    """Return {action, label} — the single next thing the user controls."""
    if stage == "draft":
        return {"action": "run_backtest", "label": "Run a backtest"}
    if stage == "backtested":
        if not gates.get("enough_trades", False):
            return {
                "action": "run_backtest",
                "label": "Widen the test (more dates/symbols) for a trustworthy sample",
            }
        return {"action": "run_oos_test", "label": "Run the out-of-sample test"}
    if stage == "oos_passed":
        return {"action": "start_forward_test", "label": "Start a forward test"}
    if stage == "forward":
        return {"action": "promote_strategy", "label": "Promote to deployable"}
    if stage == "deployable":
        return {"action": "deploy_strategy", "label": "Deploy (paper or live)"}
    if stage == "bayn_eligible":
        if gates.get("submitted_to_bayn", False):
            return {"action": "none", "label": "Submitted to the Bayn desk"}
        return {"action": "submit_to_bayn", "label": "Submit to the Bayn desk"}
    return {"action": "none", "label": ""}
