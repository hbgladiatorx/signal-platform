"""TradingManager — routes an order to the right broker and persists it.

This is the seam between the HTTP layer and the brokers. Given a trading
account row it:

  1. builds the matching broker (paper simulation or live Binance.US),
  2. resolves live credentials from the account's linked ``api_credentials``
     row (decrypted) or, failing that, environment variables,
  3. transmits/simulates the order,
  4. writes the order + fills, and updates the account's cash balance and the
     per-symbol position for whatever filled.

All DB writes happen on the caller-supplied ``AsyncSession`` so the HTTP
request commits them atomically.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from packages.core.encryption import decrypt_json
from packages.execution.base import BrokerAdapter, BrokerError
from packages.execution.binance_broker import BinanceUSLiveBroker
from packages.execution.paper import PaperBroker
from packages.execution.pricing import (
    BinanceTickerPriceSource,
    ChainedPriceSource,
    DBPriceSource,
)
from packages.execution.types import (
    ExecutionMode,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Side,
)

_ZERO = Decimal("0")


class TradingManager:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Broker construction
    # ------------------------------------------------------------------
    async def _resolve_live_credentials(
        self, session: AsyncSession, account: dict[str, Any]
    ) -> tuple[str, str]:
        """Return (api_key, api_secret) for a live account.

        Priority: the account's linked credential → the user's first stored
        binanceus credential → env vars. Raises BrokerError if none resolve.
        """
        cred_id = account.get("credential_id")
        row = None
        if cred_id is not None:
            row = (
                await session.execute(
                    text("SELECT encrypted_payload FROM api_credentials WHERE id = :id"),
                    {"id": cred_id},
                )
            ).first()
        if row is None:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT encrypted_payload FROM api_credentials
                        WHERE user_id = :uid AND service = 'binanceus'
                        ORDER BY created_at ASC LIMIT 1
                        """
                    ),
                    {"uid": account["user_id"]},
                )
            ).first()
        if row is not None:
            payload = decrypt_json(bytes(row[0]))
            api_key = payload.get("api_key") or payload.get("apiKey", "")
            secret = payload.get("secret_key") or payload.get("secret", "")
            if api_key and secret:
                return api_key, secret

        api_key = os.environ.get("BINANCEUS_API_KEY", "")
        secret = os.environ.get("BINANCEUS_API_SECRET", "")
        if api_key and secret:
            return api_key, secret
        raise BrokerError(
            "No Binance.US credentials available for this live account "
            "(no linked credential, no stored binanceus key, no env fallback)."
        )

    async def _build_broker(
        self, session: AsyncSession, account: dict[str, Any]
    ) -> BrokerAdapter:
        mode = ExecutionMode(account["mode"])
        if mode == ExecutionMode.PAPER:
            price_source = ChainedPriceSource(
                DBPriceSource(self._engine),
                BinanceTickerPriceSource(),
            )
            return PaperBroker(
                price_source,
                venue=account["venue"],
                fee_bps=int(account["fee_bps"]),
                slippage_bps=int(account["slippage_bps"]),
                quote_currency=account["quote_currency"],
            )
        api_key, secret = await self._resolve_live_credentials(session, account)
        return BinanceUSLiveBroker(api_key, secret)

    async def build_broker(
        self, session: AsyncSession, account: dict[str, Any]
    ) -> BrokerAdapter:
        """Public: construct the broker for an account (paper or live)."""
        return await self._build_broker(session, account)

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------
    async def place_order(
        self,
        session: AsyncSession,
        *,
        account: dict[str, Any],
        instrument: dict[str, Any],
        side: Side,
        order_type: OrderType,
        quantity: Decimal,
        limit_price: Decimal | None,
    ) -> dict[str, Any]:
        """Place an order for an account and persist the outcome."""
        client_order_id = f"sp-{uuid.uuid4().hex[:24]}"
        request = OrderRequest(
            canonical_symbol=instrument["canonical_symbol"],
            native_symbol=instrument["native_symbol"],
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            client_order_id=client_order_id,
        )

        broker = await self._build_broker(session, account)
        try:
            try:
                result = await broker.place_order(request)
            except BrokerError as e:
                # Persist a rejected order so the failure is auditable.
                return await self._persist_order(
                    session,
                    account=account,
                    instrument=instrument,
                    request=request,
                    result=OrderResult(
                        client_order_id=client_order_id,
                        status=OrderStatus.REJECTED,
                        filled_quantity=_ZERO,
                        avg_fill_price=None,
                        fees=_ZERO,
                        fee_currency=account["quote_currency"],
                        error_message=str(e),
                    ),
                )
            return await self._persist_order(
                session,
                account=account,
                instrument=instrument,
                request=request,
                result=result,
            )
        finally:
            await broker.close()

    async def _persist_order(
        self,
        session: AsyncSession,
        *,
        account: dict[str, Any],
        instrument: dict[str, Any],
        request: OrderRequest,
        result: OrderResult,
    ) -> dict[str, Any]:
        order_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO orders (
                        account_id, user_id, org_id, canonical_symbol,
                        native_symbol, side, order_type, quantity, limit_price,
                        mode, status, filled_quantity, avg_fill_price, fees,
                        fee_currency, client_order_id, venue_order_id, error_message
                    ) VALUES (
                        :account_id, :user_id, :org_id, :canonical_symbol,
                        :native_symbol, :side, :order_type, :quantity, :limit_price,
                        :mode, :status, :filled_quantity, :avg_fill_price, :fees,
                        :fee_currency, :client_order_id, :venue_order_id, :error_message
                    ) RETURNING id
                    """
                ),
                {
                    "account_id": account["id"],
                    "user_id": account["user_id"],
                    "org_id": account["org_id"],
                    "canonical_symbol": request.canonical_symbol,
                    "native_symbol": request.native_symbol,
                    "side": request.side.value,
                    "order_type": request.order_type.value,
                    "quantity": request.quantity,
                    "limit_price": request.limit_price,
                    "mode": account["mode"],
                    "status": result.status.value,
                    "filled_quantity": result.filled_quantity,
                    "avg_fill_price": result.avg_fill_price,
                    "fees": result.fees,
                    "fee_currency": result.fee_currency or None,
                    "client_order_id": result.client_order_id,
                    "venue_order_id": result.venue_order_id,
                    "error_message": result.error_message,
                },
            )
        ).scalar_one()

        for fill in result.fills:
            await session.execute(
                text(
                    """
                    INSERT INTO order_fills (
                        order_id, account_id, ts, price, quantity, fee,
                        fee_currency, venue_fill_id
                    ) VALUES (
                        :order_id, :account_id, :ts, :price, :quantity, :fee,
                        :fee_currency, :venue_fill_id
                    )
                    """
                ),
                {
                    "order_id": order_id,
                    "account_id": account["id"],
                    "ts": fill.ts,
                    "price": fill.price,
                    "quantity": fill.quantity,
                    "fee": fill.fee,
                    "fee_currency": fill.fee_currency or None,
                    "venue_fill_id": fill.venue_fill_id,
                },
            )

        if result.filled_quantity > 0 and result.avg_fill_price is not None:
            await self._apply_fills_to_book(
                session,
                account=account,
                instrument=instrument,
                side=request.side,
                result=result,
            )

        row = (
            await session.execute(
                text("SELECT * FROM orders WHERE id = :id"), {"id": order_id}
            )
        ).mappings().first()
        return dict(row) if row else {}

    async def _apply_fills_to_book(
        self,
        session: AsyncSession,
        *,
        account: dict[str, Any],
        instrument: dict[str, Any],
        side: Side,
        result: OrderResult,
    ) -> None:
        """Update cash balance + position from an order's aggregate fills."""
        qty = result.filled_quantity
        price = result.avg_fill_price
        assert price is not None
        notional = price * qty
        fee = result.fees
        base = (instrument.get("base") or "").upper()
        quote = (instrument.get("quote") or account["quote_currency"]).upper()
        fee_ccy = (result.fee_currency or "").upper()

        # Position bookkeeping
        existing = (
            await session.execute(
                text(
                    """
                    SELECT quantity, avg_entry_price, realized_pnl
                    FROM trading_positions
                    WHERE account_id = :aid AND canonical_symbol = :sym
                    """
                ),
                {"aid": account["id"], "sym": instrument["canonical_symbol"]},
            )
        ).first()
        old_qty = Decimal(str(existing[0])) if existing else _ZERO
        old_avg = Decimal(str(existing[1])) if existing else _ZERO
        realized = Decimal(str(existing[2])) if existing else _ZERO

        cash_delta = _ZERO
        if side == Side.BUY:
            received_qty = qty
            # Base-asset fees reduce the units actually received.
            if fee_ccy and fee_ccy == base:
                received_qty -= fee
            new_qty = old_qty + received_qty
            new_avg = (
                (old_qty * old_avg + received_qty * price) / new_qty
                if new_qty > 0
                else _ZERO
            )
            cash_delta -= notional
            if fee_ccy == quote:
                cash_delta -= fee
        else:  # SELL
            new_qty = old_qty - qty
            new_avg = old_avg if new_qty > 0 else _ZERO
            realized += (price - old_avg) * qty
            cash_delta += notional
            if fee_ccy == quote:
                cash_delta -= fee
                realized -= fee

        await session.execute(
            text(
                """
                INSERT INTO trading_positions
                    (account_id, canonical_symbol, quantity, avg_entry_price,
                     realized_pnl, updated_at)
                VALUES (:aid, :sym, :qty, :avg, :realized, now())
                ON CONFLICT (account_id, canonical_symbol) DO UPDATE SET
                    quantity = EXCLUDED.quantity,
                    avg_entry_price = EXCLUDED.avg_entry_price,
                    realized_pnl = EXCLUDED.realized_pnl,
                    updated_at = now()
                """
            ),
            {
                "aid": account["id"],
                "sym": instrument["canonical_symbol"],
                "qty": new_qty,
                "avg": new_avg,
                "realized": realized,
            },
        )

        # Cash: authoritative for paper; a best-effort mirror for live.
        await session.execute(
            text(
                """
                UPDATE trading_accounts
                SET cash_balance = cash_balance + :delta, updated_at = now()
                WHERE id = :aid
                """
            ),
            {"delta": cash_delta, "aid": account["id"]},
        )

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------
    async def cancel_order(
        self, session: AsyncSession, *, account: dict[str, Any], order: dict[str, Any]
    ) -> dict[str, Any]:
        broker = await self._build_broker(session, account)
        try:
            result = await broker.cancel_order(
                native_symbol=order["native_symbol"],
                venue_order_id=order.get("venue_order_id"),
                client_order_id=order["client_order_id"],
            )
        finally:
            await broker.close()

        await session.execute(
            text(
                """
                UPDATE orders
                SET status = :status, updated_at = now()
                WHERE id = :id
                """
            ),
            {"status": result.status.value, "id": order["id"]},
        )
        row = (
            await session.execute(
                text("SELECT * FROM orders WHERE id = :id"), {"id": order["id"]}
            )
        ).mappings().first()
        return dict(row) if row else {}
