"""
WebSocket endpoint for live market data.

Auth flow (first-message authentication):
  1. Client opens wss connection to /ws
  2. Client sends first message: {"type": "auth", "token": "<JWT>"}
  3. Server verifies JWT; on failure, sends {"type":"error",...} and closes
  4. On success, server sends {"type":"auth.ok"}
  5. Client may send {"type": "subscribe", "symbol": "BTC-USDT@BINANCEUS"}
  6. Server begins broadcasting trade and quote events for that symbol

Connection close cleans up all subscriptions automatically.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from services.api.auth import verify_token
from services.api.redis_subscriber import broadcaster

logger = logging.getLogger(__name__)

router = APIRouter()


async def _send_error(websocket: WebSocket, message: str) -> None:
    try:
        await websocket.send_text(
            json.dumps({"type": "error", "message": message})
        )
    except Exception:
        pass


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()

    # ----- Step 1: authenticate -----
    try:
        first = await websocket.receive_text()
    except WebSocketDisconnect:
        return

    try:
        first_msg = json.loads(first)
    except json.JSONDecodeError:
        await _send_error(websocket, "first message must be JSON")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if first_msg.get("type") != "auth" or not first_msg.get("token"):
        await _send_error(
            websocket, "first message must be {type: 'auth', token: '...'}"
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        claims = await verify_token(first_msg["token"])
    except Exception as exc:
        await _send_error(websocket, f"auth failed: {exc}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.send_text(
        json.dumps(
            {
                "type": "auth.ok",
                "sub": claims.get("sub"),
            }
        )
    )

    # ----- Step 2: message loop -----
    subscribed_symbols: set[str] = set()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(websocket, "message must be JSON")
                continue

            mtype = msg.get("type")

            if mtype == "subscribe":
                symbol = msg.get("symbol")
                if not symbol or not isinstance(symbol, str):
                    await _send_error(websocket, "subscribe requires 'symbol'")
                    continue
                await broadcaster.subscribe(symbol, websocket)
                subscribed_symbols.add(symbol)
                await websocket.send_text(
                    json.dumps({"type": "subscribed", "symbol": symbol})
                )

            elif mtype == "unsubscribe":
                symbol = msg.get("symbol")
                if not symbol or not isinstance(symbol, str):
                    await _send_error(websocket, "unsubscribe requires 'symbol'")
                    continue
                await broadcaster.unsubscribe(symbol, websocket)
                subscribed_symbols.discard(symbol)
                await websocket.send_text(
                    json.dumps({"type": "unsubscribed", "symbol": symbol})
                )

            elif mtype == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

            else:
                await _send_error(websocket, f"unknown message type: {mtype}")

    except WebSocketDisconnect:
        logger.info(
            "ws disconnect symbols=%s", sorted(subscribed_symbols)
        )
    except Exception:
        logger.exception("ws unexpected error")
    finally:
        await broadcaster.unsubscribe_all(websocket)
