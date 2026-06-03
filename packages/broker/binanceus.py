"""Binance.US spot execution adapter — REAL MONEY.

Docs: https://docs.binance.us/

Unlike AlpacaBroker, Binance.US spot has **no paper/sandbox** — every order this
adapter submits trades real funds on the live exchange. `paper` is therefore
False, and the live-trading runner only constructs this for sessions a user
explicitly created as mode='live'. Guardrails (global kill-switch, per-session
daily-loss halt) live in packages/livetrade and gate submission upstream of here.

Execution: signed REST (HMAC-SHA256 over the query string, `X-MBX-APIKEY`
header). Fills: the account user-data WebSocket stream (`executionReport`
events), with a REST sweep in the reconciler to cover the stream's no-replay gap.

Spot has no "positions" endpoint — holdings are derived from account balances
(base-asset balance ⇒ a position in `{BASE}-USDT@BINANCEUS`).

broker_order_id is encoded as "<NATIVE_SYMBOL>:<orderId>" because Binance's
order endpoints require the symbol alongside the id; the colon-packed form lets
cancel/get/sweep recover it from the single id the runner threads through.

Symbol mapping:
  'BTC-USDT@BINANCEUS' <-> 'BTCUSDT'   (quote kept as-is; USDT stays USDT)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlencode

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

REST_BASE = "https://api.binance.us"
WS_BASE = "wss://stream.binance.us:9443/ws"
VENUE = "BINANCEUS"

# Quote assets we recognize, longest-first so 'USDT'/'USDC' match before 'USD'.
_QUOTE_ASSETS = ("USDT", "USDC", "USD", "BTC", "ETH")
# Treated as cash for account snapshots.
_CASH_ASSETS = ("USDT", "USD", "USDC")

# Binance spot order status -> platform-normalized status.
_STATUS_MAP: dict[str, str] = {
    "NEW": "accepted",
    "PARTIALLY_FILLED": "partially_filled",
    "FILLED": "filled",
    "CANCELED": "canceled",
    "PENDING_CANCEL": "accepted",
    "REJECTED": "rejected",
    "EXPIRED": "expired",
    "EXPIRED_IN_MATCH": "expired",
}

# Binance execution type (x) -> the lifecycle category the reconciler reacts to.
_EXEC_EVENT_MAP: dict[str, str] = {
    "NEW": "new",
    "CANCELED": "canceled",
    "REJECTED": "rejected",
    "EXPIRED": "expired",
    "TRADE": "fill",          # refined to partial_fill below when not fully filled
    "REPLACED": "replaced",
    "TRADE_PREVENTION": "expired",
}

# Keepalive the user-data listenKey well inside Binance's 60-minute expiry.
_LISTENKEY_KEEPALIVE_S = 30 * 60


def _to_decimal(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    return Decimal(str(v))


class BinanceUSBroker(BrokerAdapter):
    """Binance.US spot execution adapter. REAL MONEY — there is no paper mode."""

    venue = VENUE

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        recv_window: int = 5000,
    ) -> None:
        if not api_key or not secret_key:
            raise ConfigError("BinanceUSBroker requires api_key and secret_key.")
        # Spot trades real funds; expose paper=False so callers can assert intent.
        self.paper = False
        self._key = api_key
        self._secret = secret_key.encode()
        self._recv_window = recv_window
        self._client = httpx.AsyncClient(
            base_url=REST_BASE,
            headers={"X-MBX-APIKEY": api_key},
            timeout=httpx.Timeout(15.0),
        )
        # serverTime - localTime(ms); applied to every signed timestamp so a
        # drifting host clock doesn't trip Binance's recvWindow check (-1021).
        self._time_offset_ms: int | None = None
        # symbol -> {"step": Decimal, "tick": Decimal, "min_qty": Decimal,
        #            "min_notional": Decimal}  cached from exchangeInfo.
        self._filters: dict[str, dict[str, Decimal]] = {}
        # base asset -> last price cache for equity MTM (monotonic ts, price).
        self._price_cache: dict[str, tuple[float, Decimal]] = {}

    # ============================================================
    # Symbol translation
    # ============================================================
    def to_native_symbol(self, canonical_symbol: str) -> str:
        """'BTC-USDT@BINANCEUS' -> 'BTCUSDT'."""
        if "@" not in canonical_symbol:
            raise AdapterError(
                f"canonical symbol missing venue suffix: {canonical_symbol}"
            )
        symbol_part, venue = canonical_symbol.split("@", 1)
        if venue != VENUE:
            raise AdapterError(f"venue mismatch: {venue} (expected {VENUE})")
        return symbol_part.replace("-", "")

    def to_canonical_symbol(
        self, native_symbol: str, asset_class: AssetClass = AssetClass.CRYPTO_SPOT
    ) -> str:
        """'BTCUSDT' -> 'BTC-USDT@BINANCEUS'."""
        base, quote = _split_native(native_symbol)
        if base:
            return f"{base}-{quote}@{VENUE}"
        return native_symbol

    def _asset_to_canonical(self, asset: str, quote: str = "USDT") -> str:
        return f"{asset.upper()}-{quote}@{VENUE}"

    # ============================================================
    # Execution
    # ============================================================
    async def submit_order(self, req: BrokerOrderRequest) -> BrokerOrder:
        native = self.to_native_symbol(req.canonical_symbol)
        qty = await self._round_qty(native, req.quantity)
        params: dict[str, Any] = {
            "symbol": native,
            "side": req.side.value.upper(),       # buy/sell -> BUY/SELL
            "type": req.order_type.value.upper(),  # market/limit -> MARKET/LIMIT
            "quantity": _fmt(qty),
            "newClientOrderId": req.client_order_id,
            "newOrderRespType": "RESULT",
        }
        if req.order_type == OrderType.LIMIT:
            if req.limit_price is None:
                raise AdapterError("limit order requires limit_price")
            params["timeInForce"] = "GTC"
            params["price"] = _fmt(await self._round_price(native, req.limit_price))

        try:
            data = await self._signed("POST", "/api/v3/order", params)
        except _BinanceError as e:
            # -2010 "Duplicate order sent." → idempotent re-submit; fetch existing.
            if e.code == -2010 and "duplicate" in e.message.lower():
                existing = await self._get_order_native(
                    native, orig_client_order_id=req.client_order_id
                )
                if existing is not None:
                    log.info(
                        "binanceus.submit.idempotent_hit",
                        client_order_id=req.client_order_id,
                    )
                    return existing
            raise AdapterError(
                f"Binance.US rejected order ({e.code}): {e.message}"
            ) from e
        return self._parse_order(data, req.canonical_symbol)

    async def cancel_order(self, broker_order_id: str) -> None:
        native, order_id = _unpack_broker_id(broker_order_id)
        if native is None or order_id is None:
            raise AdapterError(
                f"cancel_order needs a '<symbol>:<orderId>' id, got {broker_order_id!r}"
            )
        try:
            await self._signed(
                "DELETE", "/api/v3/order", {"symbol": native, "orderId": order_id}
            )
        except _BinanceError as e:
            # -2011 "Unknown order sent." = already terminal/canceled — no-op.
            if e.code == -2011:
                return
            raise AdapterError(
                f"Binance.US cancel_order failed ({e.code}): {e.message}"
            ) from e

    async def get_order(
        self,
        *,
        broker_order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> BrokerOrder | None:
        if not broker_order_id:
            # A bare client_order_id can't be looked up on Binance (symbol is
            # required). The reconciler sweep always passes the colon-packed id.
            raise AdapterError(
                "BinanceUSBroker.get_order requires a '<symbol>:<orderId>' broker_order_id"
            )
        native, order_id = _unpack_broker_id(broker_order_id)
        if native is None or order_id is None:
            raise AdapterError(f"malformed broker_order_id: {broker_order_id!r}")
        return await self._get_order_native(native, order_id=order_id)

    async def _get_order_native(
        self,
        native: str,
        *,
        order_id: str | None = None,
        orig_client_order_id: str | None = None,
    ) -> BrokerOrder | None:
        params: dict[str, Any] = {"symbol": native}
        if order_id is not None:
            params["orderId"] = order_id
        elif orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        else:
            raise AdapterError("_get_order_native needs order_id or orig_client_order_id")
        try:
            data = await self._signed("GET", "/api/v3/order", params)
        except _BinanceError as e:
            if e.code == -2013:  # "Order does not exist."
                return None
            raise AdapterError(
                f"Binance.US get_order failed ({e.code}): {e.message}"
            ) from e
        return self._parse_order(data)

    # ============================================================
    # Account / positions
    # ============================================================
    async def list_positions(self) -> list[BrokerPosition]:
        data = await self._signed("GET", "/api/v3/account", {})
        out: list[BrokerPosition] = []
        for bal in data.get("balances", []):
            asset = bal.get("asset", "")
            qty = (_to_decimal(bal.get("free")) or Decimal(0)) + (
                _to_decimal(bal.get("locked")) or Decimal(0)
            )
            if qty == 0 or asset.upper() in _CASH_ASSETS:
                continue
            out.append(
                BrokerPosition(
                    canonical_symbol=self._asset_to_canonical(asset),
                    quantity=qty,
                    avg_entry_price=Decimal(0),  # not available from balances
                    market_value=None,
                )
            )
        return out

    async def get_account(self) -> BrokerAccount:
        data = await self._signed("GET", "/api/v3/account", {})
        cash = Decimal(0)
        holdings: dict[str, Decimal] = {}
        for bal in data.get("balances", []):
            asset = (bal.get("asset") or "").upper()
            qty = (_to_decimal(bal.get("free")) or Decimal(0)) + (
                _to_decimal(bal.get("locked")) or Decimal(0)
            )
            if qty == 0:
                continue
            if asset in _CASH_ASSETS:
                cash += qty
            else:
                holdings[asset] = qty

        # Equity = cash + mark-to-market of non-cash holdings. Best-effort: if
        # a price lookup fails we just under-count rather than block the snapshot.
        positions_value = Decimal(0)
        for asset, qty in holdings.items():
            price = await self._mark_price(f"{asset}USDT")
            if price is not None:
                positions_value += qty * price
        equity = cash + positions_value
        return BrokerAccount(cash=cash, equity=equity, buying_power=cash)

    async def _mark_price(self, native: str) -> Decimal | None:
        now = time.monotonic()
        cached = self._price_cache.get(native)
        if cached is not None and now - cached[0] < 10.0:
            return cached[1]
        try:
            resp = await self._client.get(
                "/api/v3/ticker/price", params={"symbol": native}
            )
            if resp.status_code >= 400:
                return None
            price = _to_decimal(resp.json().get("price"))
        except Exception:  # noqa: BLE001
            return None
        if price is not None:
            self._price_cache[native] = (now, price)
        return price

    # ============================================================
    # User-data stream (executionReport over WebSocket)
    # ============================================================
    async def stream_trade_updates(self) -> AsyncIterator[TradeUpdate]:
        backoff = 1
        while True:
            listen_key: str | None = None
            keepalive: asyncio.Task | None = None
            try:
                listen_key = await self._create_listen_key()
                keepalive = asyncio.create_task(self._keepalive_loop(listen_key))
                url = f"{WS_BASE}/{listen_key}"
                log.info("binanceus.stream.connecting")
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=20
                ) as ws:
                    log.info("binanceus.stream.listening")
                    backoff = 1
                    async for raw in ws:
                        msg = self._unpack(raw)
                        if msg is None or msg.get("e") != "executionReport":
                            continue
                        upd = self._parse_execution_report(msg)
                        if upd is not None:
                            yield upd
            except (websockets.ConnectionClosed, OSError) as e:
                log.warning(
                    "binanceus.stream.disconnected", error=str(e), backoff=backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            finally:
                if keepalive is not None:
                    keepalive.cancel()
                if listen_key is not None:
                    await self._close_listen_key(listen_key)

    async def _create_listen_key(self) -> str:
        resp = await self._client.post("/api/v3/userDataStream")
        if resp.status_code >= 400:
            raise AdapterError(
                f"Binance.US listenKey create failed ({resp.status_code}): {resp.text}"
            )
        return resp.json()["listenKey"]

    async def _keepalive_loop(self, listen_key: str) -> None:
        while True:
            await asyncio.sleep(_LISTENKEY_KEEPALIVE_S)
            try:
                await self._client.put(
                    "/api/v3/userDataStream", params={"listenKey": listen_key}
                )
            except Exception as e:  # noqa: BLE001
                log.warning("binanceus.stream.keepalive_failed", error=str(e))

    async def _close_listen_key(self, listen_key: str) -> None:
        try:
            await self._client.delete(
                "/api/v3/userDataStream", params={"listenKey": listen_key}
            )
        except Exception:  # noqa: BLE001
            pass

    async def close(self) -> None:
        await self._client.aclose()

    # ============================================================
    # Signed request plumbing
    # ============================================================
    async def _signed(
        self, method: str, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        params = dict(params)
        params["timestamp"] = await self._timestamp_ms()
        params["recvWindow"] = self._recv_window
        query = urlencode(params)
        signature = hmac.new(self._secret, query.encode(), hashlib.sha256).hexdigest()
        url = f"{path}?{query}&signature={signature}"
        resp = await self._client.request(method, url)
        if resp.status_code >= 400:
            code, message = _binance_error(resp)
            raise _BinanceError(resp.status_code, code, message)
        return resp.json()

    async def _timestamp_ms(self) -> int:
        if self._time_offset_ms is None:
            await self._sync_time()
        return int(time.time() * 1000) + (self._time_offset_ms or 0)

    async def _sync_time(self) -> None:
        try:
            resp = await self._client.get("/api/v3/time")
            server_ms = int(resp.json()["serverTime"])
            self._time_offset_ms = server_ms - int(time.time() * 1000)
        except Exception as e:  # noqa: BLE001
            log.warning("binanceus.time_sync_failed", error=str(e))
            self._time_offset_ms = 0

    # ============================================================
    # exchangeInfo precision
    # ============================================================
    async def _symbol_filters(self, native: str) -> dict[str, Decimal]:
        cached = self._filters.get(native)
        if cached is not None:
            return cached
        try:
            resp = await self._client.get(
                "/api/v3/exchangeInfo", params={"symbol": native}
            )
            info = resp.json()["symbols"][0]
        except Exception as e:  # noqa: BLE001
            log.warning("binanceus.exchange_info_failed", symbol=native, error=str(e))
            return {}
        f: dict[str, Decimal] = {}
        for filt in info.get("filters", []):
            ftype = filt.get("filterType")
            if ftype == "LOT_SIZE":
                f["step"] = Decimal(str(filt["stepSize"]))
                f["min_qty"] = Decimal(str(filt["minQty"]))
            elif ftype == "PRICE_FILTER":
                f["tick"] = Decimal(str(filt["tickSize"]))
            elif ftype in ("MIN_NOTIONAL", "NOTIONAL"):
                mn = filt.get("minNotional") or filt.get("notional")
                if mn is not None:
                    f["min_notional"] = Decimal(str(mn))
        self._filters[native] = f
        return f

    async def _round_qty(self, native: str, qty: Decimal) -> Decimal:
        step = (await self._symbol_filters(native)).get("step")
        if not step or step == 0:
            return qty
        # Floor to the step so we never request more than the strategy intended.
        return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step

    async def _round_price(self, native: str, price: Decimal) -> Decimal:
        tick = (await self._symbol_filters(native)).get("tick")
        if not tick or tick == 0:
            return price
        return (price / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick

    # ============================================================
    # Parsing
    # ============================================================
    @staticmethod
    def _unpack(raw: Any) -> dict[str, Any] | None:
        try:
            return json.loads(raw)
        except Exception as e:  # noqa: BLE001 — never let a bad frame kill the loop
            log.warning("binanceus.stream.unpack_error", error=str(e))
            return None

    def _parse_order(
        self, o: dict[str, Any], canonical_hint: str | None = None
    ) -> BrokerOrder:
        native = o.get("symbol", "")
        canonical = canonical_hint or self.to_canonical_symbol(native)
        executed = _to_decimal(o.get("executedQty")) or Decimal(0)
        quote_filled = _to_decimal(o.get("cummulativeQuoteQty"))
        avg = None
        if executed > 0 and quote_filled is not None:
            avg = quote_filled / executed
        elif o.get("fills"):
            avg = _avg_from_fills(o["fills"])
        return BrokerOrder(
            broker_order_id=_pack_broker_id(native, o.get("orderId")),
            client_order_id=str(o.get("clientOrderId", "")),
            canonical_symbol=canonical,
            side=OrderSide(str(o.get("side", "BUY")).lower()),
            order_type=OrderType(str(o.get("type", "MARKET")).lower()),
            quantity=_to_decimal(o.get("origQty")) or Decimal(0),
            filled_quantity=executed,
            avg_fill_price=avg,
            limit_price=_nonzero(_to_decimal(o.get("price"))),
            status=_STATUS_MAP.get(o.get("status", ""), "accepted"),
            submitted_at=_parse_ms(o.get("transactTime") or o.get("time")),
            raw=o,
        )

    def _parse_execution_report(self, d: dict[str, Any]) -> TradeUpdate | None:
        native = d.get("s", "")
        exec_type = d.get("x", "")
        order_status = d.get("X", "")
        event = _EXEC_EVENT_MAP.get(exec_type, exec_type.lower())
        if event == "fill" and order_status != "FILLED":
            event = "partial_fill"
        # On cancel/replace reports the original client id is in 'C'; otherwise 'c'.
        coid = d.get("C") or d.get("c") or ""
        trade_id = d.get("t")
        return TradeUpdate(
            event=event,
            broker_order_id=_pack_broker_id(native, d.get("i")),
            client_order_id=str(coid),
            canonical_symbol=self.to_canonical_symbol(native),
            order_status=_STATUS_MAP.get(order_status, ""),
            filled_qty=_to_decimal(d.get("z")),
            fill_qty_delta=_to_decimal(d.get("l")),
            fill_price=_nonzero(_to_decimal(d.get("L"))),
            fee=_to_decimal(d.get("n")) or Decimal(0),
            reason=d.get("r") if d.get("r") not in (None, "NONE") else None,
            ts=_parse_ms(d.get("T") or d.get("E")) or datetime.now(tz=timezone.utc),
            # execution_id keys the reconciler's per-fill dedup.
            raw={**d, "execution_id": str(trade_id) if trade_id not in (None, -1) else ""},
        )


# ============================================================
# Module-level helpers
# ============================================================
class _BinanceError(Exception):
    """Carries Binance's numeric error code so callers can branch on it."""

    def __init__(self, http_status: int, code: int, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.http_status = http_status
        self.code = code
        self.message = message


def _binance_error(resp: httpx.Response) -> tuple[int, str]:
    try:
        body = resp.json()
        return int(body.get("code", 0)), str(body.get("msg", resp.text))
    except Exception:  # noqa: BLE001
        return 0, resp.text


def _pack_broker_id(native: str, order_id: Any) -> str:
    return f"{native}:{order_id}"


def _unpack_broker_id(packed: str) -> tuple[str | None, str | None]:
    if ":" not in packed:
        return None, None
    native, order_id = packed.split(":", 1)
    return (native or None), (order_id or None)


def _split_native(native: str) -> tuple[str, str]:
    """'BTCUSDT' -> ('BTC', 'USDT'). ('', '') if no known quote suffix."""
    up = native.upper()
    for q in _QUOTE_ASSETS:
        if up.endswith(q) and len(up) > len(q):
            return up[: -len(q)], q
    return "", ""


def _avg_from_fills(fills: list[dict[str, Any]]) -> Decimal | None:
    total_qty = Decimal(0)
    total_quote = Decimal(0)
    for fl in fills:
        q = _to_decimal(fl.get("qty")) or Decimal(0)
        p = _to_decimal(fl.get("price")) or Decimal(0)
        total_qty += q
        total_quote += q * p
    return (total_quote / total_qty) if total_qty > 0 else None


def _nonzero(v: Decimal | None) -> Decimal | None:
    if v is None or v == 0:
        return None
    return v


def _fmt(v: Decimal) -> str:
    """Plain-decimal string (no scientific notation) for Binance params."""
    return format(v.normalize(), "f")


def _parse_ms(v: Any) -> datetime | None:
    if v is None:
        return None
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None
