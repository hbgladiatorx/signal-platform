"""Shared Alpaca broker logic for both the paper and live adapters.

``BaseAlpacaBroker`` holds everything common to paper and live execution; the
REST/WS base URLs and the ``paper`` flag are supplied by the subclass. This is
how we add a live broker WITHOUT weakening the paper-only lock in
``packages/broker/alpaca.py`` — the live host appears only in
``packages/broker/alpaca_live.py``.

Supports equities, crypto, and single-leg options. Option canonical symbols are
OCC-style (``AAPL250117C00150000@ALPACA``); the OCC string is also the Alpaca
native symbol, so order placement reuses the equity path with the same
``/v2/orders`` endpoint.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import structlog
import websockets

from packages.broker.base import (
    BrokerAccount,
    BrokerAdapter,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
    TradeUpdate,
)
from packages.core.exceptions import AdapterError, ConfigError
from packages.core.types import AssetClass
from packages.strategy.base import OrderSide, OrderType

log = structlog.get_logger(__name__)

# Alpaca order status -> platform-normalized status.
_STATUS_MAP: dict[str, str] = {
    "new": "accepted",
    "accepted": "accepted",
    "pending_new": "accepted",
    "accepted_for_bidding": "accepted",
    "partially_filled": "partially_filled",
    "filled": "filled",
    "done_for_day": "accepted",
    "canceled": "canceled",
    "pending_cancel": "accepted",
    "expired": "expired",
    "replaced": "canceled",
    "pending_replace": "accepted",
    "rejected": "rejected",
    "suspended": "accepted",
    "calculated": "accepted",
    "stopped": "accepted",
    "held": "accepted",
}

_TERMINAL_EVENTS = {"canceled", "expired", "rejected"}
_OPTION_ASSET_CLASSES = {"option", "us_option"}


def _to_decimal(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    return Decimal(str(v))


class BaseAlpacaBroker(BrokerAdapter):
    """Common Alpaca execution logic; URLs + paper flag come from the subclass."""

    venue = "ALPACA"

    def __init__(
        self,
        api_key_id: str,
        secret_key: str,
        *,
        rest_base: str,
        stream_url: str,
        paper: bool,
    ) -> None:
        if not api_key_id or not secret_key:
            raise ConfigError("Alpaca broker requires api_key_id and secret_key.")
        self.paper = paper
        self._rest_base = rest_base
        self._stream_url = stream_url
        self._key = api_key_id
        self._secret = secret_key
        self._headers = {
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self._client = httpx.AsyncClient(
            base_url=rest_base,
            headers=self._headers,
            timeout=httpx.Timeout(15.0),
        )
        self._clock_cache: tuple[float, bool] | None = None

    # ============================================================
    # Symbol translation
    # ============================================================
    def to_native_symbol(self, canonical_symbol: str) -> str:
        if "@" not in canonical_symbol:
            raise AdapterError(
                f"canonical symbol missing venue suffix: {canonical_symbol}"
            )
        symbol_part, venue = canonical_symbol.split("@", 1)
        if venue == "ALPACA":
            # Equity or single-leg option (OCC): pass the native symbol through.
            return symbol_part
        # Crypto from the data venue: 'BTC-USDT' -> base/quote, USDT -> USD.
        if "-" in symbol_part:
            base, quote = symbol_part.split("-", 1)
            if quote.upper() == "USDT":
                quote = "USD"
            return f"{base}/{quote}"
        return symbol_part

    def to_canonical_symbol(
        self, native_symbol: str, asset_class: AssetClass
    ) -> str:
        if asset_class == AssetClass.EQUITY:
            return f"{native_symbol}@ALPACA"
        if asset_class == AssetClass.OPTION:
            return f"{native_symbol}@ALPACA"
        if asset_class == AssetClass.CRYPTO_SPOT:
            base, quote = _split_crypto_native(native_symbol)
            if base:
                if quote == "USD":
                    quote = "USDT"
                return f"{base}-{quote}@BINANCEUS"
        return native_symbol

    # ============================================================
    # Execution
    # ============================================================
    async def submit_order(self, req: BrokerOrderRequest) -> BrokerOrder:
        # Single-leg only: we never construct multi-leg `legs[]` payloads.
        body: dict[str, Any] = {
            "symbol": self.to_native_symbol(req.canonical_symbol),
            "qty": str(req.quantity),
            "side": req.side.value,
            "type": req.order_type.value,
            "time_in_force": req.time_in_force,
            "client_order_id": req.client_order_id,
        }
        if req.order_type == OrderType.LIMIT:
            if req.limit_price is None:
                raise AdapterError("limit order requires limit_price")
            body["limit_price"] = str(req.limit_price)

        resp = await self._client.post("/v2/orders", json=body)
        if resp.status_code == 422:
            text = resp.text.lower()
            if "client_order_id" in text or "must be unique" in text:
                existing = await self.get_order(client_order_id=req.client_order_id)
                if existing is not None:
                    log.info(
                        "alpaca.submit.idempotent_hit",
                        client_order_id=req.client_order_id,
                    )
                    return existing
            raise AdapterError(f"Alpaca rejected order (422): {resp.text}")
        if resp.status_code >= 400:
            raise AdapterError(
                f"Alpaca submit_order failed ({resp.status_code}): {resp.text}"
            )
        return self._parse_order(resp.json(), req.canonical_symbol)

    async def cancel_order(self, broker_order_id: str) -> None:
        resp = await self._client.delete(f"/v2/orders/{broker_order_id}")
        if resp.status_code in (404, 422):
            return
        if resp.status_code >= 400:
            raise AdapterError(
                f"Alpaca cancel_order failed ({resp.status_code}): {resp.text}"
            )

    async def get_order(
        self,
        *,
        broker_order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> BrokerOrder | None:
        if broker_order_id:
            resp = await self._client.get(f"/v2/orders/{broker_order_id}")
        elif client_order_id:
            resp = await self._client.get(
                "/v2/orders:by_client_order_id",
                params={"client_order_id": client_order_id},
            )
        else:
            raise AdapterError("get_order requires broker_order_id or client_order_id")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise AdapterError(
                f"Alpaca get_order failed ({resp.status_code}): {resp.text}"
            )
        return self._parse_order(resp.json())

    # ============================================================
    # Account / positions
    # ============================================================
    async def list_positions(self) -> list[BrokerPosition]:
        resp = await self._client.get("/v2/positions")
        if resp.status_code >= 400:
            raise AdapterError(
                f"Alpaca list_positions failed ({resp.status_code}): {resp.text}"
            )
        out: list[BrokerPosition] = []
        for p in resp.json():
            out.append(
                BrokerPosition(
                    canonical_symbol=self._native_to_canonical_best_effort(
                        p.get("symbol", ""), p.get("asset_class")
                    ),
                    quantity=_to_decimal(p.get("qty")) or Decimal(0),
                    avg_entry_price=_to_decimal(p.get("avg_entry_price")) or Decimal(0),
                    market_value=_to_decimal(p.get("market_value")),
                )
            )
        return out

    async def is_market_open(self, *, cache_ttl_s: float = 30.0) -> bool:
        import time

        now = time.monotonic()
        if self._clock_cache is not None and now - self._clock_cache[0] < cache_ttl_s:
            return self._clock_cache[1]
        try:
            resp = await self._client.get("/v2/clock")
            is_open = bool(resp.json().get("is_open", True)) if resp.status_code < 400 else True
        except Exception:  # noqa: BLE001
            is_open = True
        self._clock_cache = (now, is_open)
        return is_open

    async def get_account(self) -> BrokerAccount:
        resp = await self._client.get("/v2/account")
        if resp.status_code >= 400:
            raise AdapterError(
                f"Alpaca get_account failed ({resp.status_code}): {resp.text}"
            )
        a = resp.json()
        return BrokerAccount(
            cash=_to_decimal(a.get("cash")) or Decimal(0),
            equity=_to_decimal(a.get("equity")) or Decimal(0),
            buying_power=_to_decimal(a.get("buying_power")) or Decimal(0),
        )

    # ============================================================
    # Trade-updates stream (JSON over WebSocket)
    # ============================================================
    async def stream_trade_updates(self) -> AsyncIterator[TradeUpdate]:
        backoff = 1
        while True:
            try:
                log.info("alpaca.stream.connecting", paper=self.paper)
                async with websockets.connect(
                    self._stream_url, ping_interval=20, ping_timeout=20
                ) as ws:
                    await ws.send(
                        json.dumps(
                            {"action": "auth", "key": self._key, "secret": self._secret}
                        )
                    )
                    await ws.send(
                        json.dumps(
                            {"action": "listen", "data": {"streams": ["trade_updates"]}}
                        )
                    )
                    log.info("alpaca.stream.listening")
                    backoff = 1
                    async for raw in ws:
                        msg = self._unpack(raw)
                        if msg is None:
                            continue
                        if msg.get("stream") != "trade_updates":
                            continue
                        upd = self._parse_trade_update(msg.get("data") or {})
                        if upd is not None:
                            yield upd
            except (websockets.ConnectionClosed, OSError) as e:
                log.warning("alpaca.stream.disconnected", error=str(e), backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def close(self) -> None:
        await self._client.aclose()

    # ============================================================
    # Parsing helpers
    # ============================================================
    @staticmethod
    def _unpack(raw: Any) -> dict[str, Any] | None:
        try:
            return json.loads(raw)
        except Exception as e:  # noqa: BLE001
            log.warning("alpaca.stream.unpack_error", error=str(e))
            return None

    def _native_to_canonical_best_effort(
        self, native: str, alpaca_asset_class: str | None
    ) -> str:
        if alpaca_asset_class in _OPTION_ASSET_CLASSES:
            ac = AssetClass.OPTION
        else:
            is_crypto = (
                alpaca_asset_class == "crypto"
                or "/" in native
                or bool(_split_crypto_native(native)[0])
            )
            ac = AssetClass.CRYPTO_SPOT if is_crypto else AssetClass.EQUITY
        try:
            return self.to_canonical_symbol(native, ac)
        except Exception:  # noqa: BLE001
            return native

    def _parse_order(
        self, o: dict[str, Any], canonical_hint: str | None = None
    ) -> BrokerOrder:
        native = o.get("symbol", "")
        canonical = canonical_hint or self._native_to_canonical_best_effort(
            native, o.get("asset_class")
        )
        return BrokerOrder(
            broker_order_id=str(o.get("id", "")),
            client_order_id=str(o.get("client_order_id", "")),
            canonical_symbol=canonical,
            side=OrderSide(o.get("side", "buy")),
            order_type=OrderType(o.get("type", o.get("order_type", "market"))),
            quantity=_to_decimal(o.get("qty")) or Decimal(0),
            filled_quantity=_to_decimal(o.get("filled_qty")) or Decimal(0),
            avg_fill_price=_to_decimal(o.get("filled_avg_price")),
            limit_price=_to_decimal(o.get("limit_price")),
            status=_STATUS_MAP.get(o.get("status", ""), o.get("status", "accepted")),
            submitted_at=_parse_ts(o.get("submitted_at") or o.get("created_at")),
            raw=o,
        )

    def _parse_trade_update(self, data: dict[str, Any]) -> TradeUpdate | None:
        order = data.get("order") or {}
        event = data.get("event", "")
        if not order:
            return None
        native = order.get("symbol", "")
        canonical = self._native_to_canonical_best_effort(
            native, order.get("asset_class")
        )
        return TradeUpdate(
            event=event,
            broker_order_id=str(order.get("id", "")),
            client_order_id=str(order.get("client_order_id", "")),
            canonical_symbol=canonical,
            order_status=_STATUS_MAP.get(
                order.get("status", ""), order.get("status", "")
            ),
            filled_qty=_to_decimal(order.get("filled_qty")),
            fill_qty_delta=_to_decimal(data.get("qty")),
            fill_price=_to_decimal(data.get("price")),
            fee=_to_decimal(data.get("fee")) or Decimal(0),
            reason=order.get("rejected_reason") or data.get("reason"),
            ts=_parse_ts(data.get("timestamp")) or datetime.now(tz=timezone.utc),
            raw=data,
        )


# Crypto quote assets Alpaca uses, longest-first so 'USDT'/'USDC' match before 'USD'.
_CRYPTO_QUOTES = ("USDT", "USDC", "USD")


def _split_crypto_native(native: str) -> tuple[str, str]:
    """Split an Alpaca crypto symbol into (base, quote). Handles 'BTC/USD' and
    'BTCUSD'. Returns ('', '') for things that don't look like crypto pairs."""
    if "/" in native:
        base, quote = native.split("/", 1)
        return base.upper(), quote.upper()
    up = native.upper()
    for q in _CRYPTO_QUOTES:
        if up.endswith(q) and len(up) > len(q):
            return up[: -len(q)], q
    return "", ""


def _parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
