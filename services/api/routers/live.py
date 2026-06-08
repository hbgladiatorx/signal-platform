"""Live-trading controls — the global kill-switch.

The kill-switch is a single platform-wide Redis flag (see packages.livetrade.
guards.KILL_SWITCH_KEY). While engaged, the paper_trader runner refuses to
submit any REAL-MONEY (mode='live') order; paper sessions are unaffected. It is
a pause, not a teardown — disengaging resumes live trading on the next bar.

Endpoints (JWT-protected):
  GET    /live/killswitch   — current state
  POST   /live/killswitch   — engage (halt all live submission)
  DELETE /live/killswitch   — disengage (resume)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from packages.livetrade.guards import KILL_SWITCH_KEY
from services.api.deps import CurrentUserRecord, get_current_user_record
from services.api.routers.backtests import _get_redis

log = logging.getLogger(__name__)
router = APIRouter(prefix="/live", tags=["live-trading"])


class KillSwitchState(BaseModel):
    engaged: bool


@router.get("/killswitch", response_model=KillSwitchState)
async def get_killswitch(
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> KillSwitchState:
    r = await _get_redis()
    return KillSwitchState(engaged=bool(await r.exists(KILL_SWITCH_KEY)))


@router.post("/killswitch", response_model=KillSwitchState)
async def engage_killswitch(
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> KillSwitchState:
    r = await _get_redis()
    await r.set(KILL_SWITCH_KEY, "1")
    log.warning("live.killswitch.engaged by user=%s", user.id)
    return KillSwitchState(engaged=True)


@router.delete("/killswitch", response_model=KillSwitchState)
async def disengage_killswitch(
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> KillSwitchState:
    r = await _get_redis()
    await r.delete(KILL_SWITCH_KEY)
    log.warning("live.killswitch.disengaged by user=%s", user.id)
    return KillSwitchState(engaged=False)
