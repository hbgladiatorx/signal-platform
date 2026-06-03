"""BinanceUSLiveBroker — real spot order execution on Binance.US.

Transmits signed REST requests to Binance.US's trade endpoints. This places
**real orders with real money**, so two guards stand in front of it:

  1. Credentials: an API key + secret are required (resolved by the caller from
     the user's encrypted ``api_credentials`` or, as a fallback, env vars).

  2. A kill-switch env flag: ``BINANCEUS_LIVE_TRADING_ENABLED`` must be set to
     "true". If it isn't, :meth:`place_order` refuses to transmit and raises
     ``BrokerError`` — the broker can be wired up and exercised in every other
     respect without a single live order leaving the box.

Signing follows the Binance spec: HMAC-SHA256 over the request query string,
keyed by the API secret, appended as the ``signature`` parameter, with the API
key sent in the ``X-MBX-APIKEY`` header.

Docs: https://docs.binance.us/#trade-order-endpoints
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import urllib.parse
from decimal import Decimal

import aiohttp

from packages.execution.base import BrokerAdapter, BrokerError
from packages.execution.types import (
    Balance,
    BrokerPosition,
    ExecutionMode,
    FillRecord,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Side,
)

BINANCE_US_BASE = "https://api.binance.us"
RECV_WINDOW_MS = 5000

# Binance order status string → platform OrderStatus.
_STATUS_MAP = {
    "NEW": OrderStatus.NEW,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELED,
    "PENDING_CANCEL": OrderStatus.CANCELED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.EXPIRED,
}

LIVE_ENABLED_ENV = "BINANCEUS_LIVE_TRADING_ENABLED"


def live_trading_enabled() -> bool:
    """True only when the operator has explicitly opted in via env."""
    return os.environ.get(LIVE_ENABLED_ENV, "false").strip().lower() == "true"


class BinanceUSLiveBroker(BrokerAdapter):
    """Signed-REST spot execution against Binance.US."""

    mode = ExecutionMode.LIVE
    venue = "BINANCEUS"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = BINANCE_US_BASE,
        session: aiohttp.ClientSession | None = None,
        recv_window_ms: int = RECV_WINDOW_MS,
    ) -> None:
        if not api_key or not api_secret:
            raise BrokerError("Binance.US live broker requires api_key and api_secret")
        self._api_key = api_key
        self._api_secret = api_secret.encode("utf-8")
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._own_session = session is None
        self._recv_window = recv_window_ms

    # ----- signing / transport -----
    def _sign(self, params: dict[str, str]) -> str:
        query = urllib.parse.urlencode(params)
        signature = hmac.new(
            self._api_secret, query.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return f"{query}&signature={signature}"

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _signed_request(
        self, method: str, path: str, params: dict[str, str]
    ) -> dict:
        params = dict(params)
        params["timestamp"] = str(int(time.time() * 1000))
        params["recvWindow"] = str(self._recv_window)
        body = self._sign(params)
        url = f"{self._base_url}{path}?{body}"
        headers = {"X-MBX-APIKEY": self._api_key}
        session = await self._get_session()
        async with session.request(
            method, url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            payload = await resp.json(content_type=None)
            if resp.status >= 400:
                code = payload.get("code") if isinstance(payload, dict) else None
                msg = payload.get("msg") if isinstance(payload, dict) else str(payload)
                raise BrokerError(
                    f"Binance.US {method} {path} failed "
                    f"(HTTP {resp.status}, code {code}): {msg}"
                )
            return payload

    # ----- result parsing -----
    @staticmethod
    def _parse_order_result(client_order_id: str, payload: dict) -> OrderResult:
        status = _STATUS_MAP.get(
            str(payload.get("status", "NEW")).upper(), OrderStatus.NEW
        )
        fills_raw = payload.get("fills") or []
        fills: list[FillRecord] = []
        total_qty = Decimal("0")
        total_quote = Decimal("0")
        total_fee = Decimal("0")
        fee_ccy = ""
        for f in fills_raw:
            price = Decimal(str(f["price"]))
            qty = Decimal(str(f["qty"]))
            fee = Decimal(str(f.get("commission", "0")))
            fee_ccy = f.get("commissionAsset", fee_ccy)
            fills.append(
                FillRecord(
                    price=price,
                    quantity=qty,
                    fee=fee,
                    fee_currency=fee_ccy,
                    venue_fill_id=str(f.get("tradeId")) if f.get("tradeId") else None,
                )
            )
            total_qty += qty
            total_quote += price * qty
            total_fee += fee

        executed_qty = Decimal(str(payload.get("executedQty", total_qty)))
        if total_qty > 0:
            avg_price = total_quote / total_qty
        else:
            cqq = payload.get("cummulativeQuoteQty")
            avg_price = (
                Decimal(str(cqq)) / executed_qty
                if cqq and executed_qty > 0
                else None
            )

        return OrderResult(
            client_order_id=str(payload.get("clientOrderId", client_order_id)),
            status=status,
            filled_quantity=executed_qty,
            avg_fill_price=avg_price,
            fees=total_fee,
            fee_currency=fee_ccy or "",
            fills=fills,
            venue_order_id=str(payload["orderId"]) if "orderId" in payload else None,
            raw=payload,
        )

    # ----- BrokerAdapter -----
    async def place_order(self, request: OrderRequest) -> OrderResult:
        if not live_trading_enabled():
            raise BrokerError(
                "Live trading is disabled. Set "
                f"{LIVE_ENABLED_ENV}=true to permit real order transmission."
            )
        params: dict[str, str] = {
            "symbol": request.native_symbol,
            "side": "BUY" if request.side == Side.BUY else "SELL",
            "quantity": format(request.quantity.normalize(), "f"),
        }
        if request.client_order_id:
            params["newClientOrderId"] = request.client_order_id
        if request.order_type == OrderType.MARKET:
            params["type"] = "MARKET"
        else:
            assert request.limit_price is not None
            params["type"] = "LIMIT"
            params["timeInForce"] = "GTC"
            params["price"] = format(request.limit_price.normalize(), "f")

        payload = await self._signed_request("POST", "/api/v3/order", params)
        return self._parse_order_result(request.client_order_id or "", payload)

    async def cancel_order(
        self,
        *,
        native_symbol: str,
        venue_order_id: str | None,
        client_order_id: str,
    ) -> OrderResult:
        params = {"symbol": native_symbol}
        if venue_order_id:
            params["orderId"] = venue_order_id
        else:
            params["origClientOrderId"] = client_order_id
        payload = await self._signed_request("DELETE", "/api/v3/order", params)
        return self._parse_order_result(client_order_id, payload)

    async def get_balances(self) -> list[Balance]:
        payload = await self._signed_request("GET", "/api/v3/account", {})
        out: list[Balance] = []
        for b in payload.get("balances", []):
            free = Decimal(str(b.get("free", "0")))
            locked = Decimal(str(b.get("locked", "0")))
            if free > 0 or locked > 0:
                out.append(Balance(asset=b["asset"], free=free, locked=locked))
        return out

    async def get_positions(self) -> list[BrokerPosition]:
        # Spot venues have no "positions"; balances are the equivalent and are
        # exposed via get_balances(). Return empty for interface compatibility.
        return []

    async def close(self) -> None:
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None
