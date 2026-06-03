"""READ-ONLY Binance.US preflight. Places NO orders, moves NO funds.

Validates a stored binanceus credential is live and trade-enabled before any
real session is started:
  1. GET /api/v3/account  — proves the key works + shows balances (read perm).
  2. POST /api/v3/order/test — proves SPOT TRADING permission + that the order
     path (signing, symbol filters, min-notional) is correct. Binance validates
     and returns {} WITHOUT creating an order.

Usage (inside the paper_trader/api container, which has the env + code):
    python -m scripts.binanceus_preflight [SYMBOL]
"""
from __future__ import annotations

import asyncio
import sys
from decimal import Decimal

from sqlalchemy import text

from packages.broker.binanceus import BinanceUSBroker
from packages.core.encryption import decrypt_json
from packages.data.db import get_engine


async def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC-USDT@BINANCEUS"
    engine = get_engine()
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT label, encrypted_payload FROM api_credentials "
                    "WHERE service = 'binanceus' ORDER BY created_at LIMIT 1"
                )
            )
        ).mappings().first()
    if row is None:
        print("NO binanceus credential stored. Add one in Settings first.")
        return
    payload = decrypt_json(bytes(row["encrypted_payload"]))
    print(f"Using credential: {row['label']!r}")

    broker = BinanceUSBroker(api_key=payload["api_key"], secret_key=payload["secret_key"])
    try:
        # 1) READ-ONLY account snapshot.
        try:
            acct = await broker.get_account()
            print("\n[1] get_account OK (read permission confirmed)")
            print(f"    cash (USD/USDT): {acct.cash}")
            print(f"    equity (MTM):    {acct.equity}")
            positions = await broker.list_positions()
            if positions:
                print("    holdings:")
                for p in positions:
                    print(f"      {p.canonical_symbol}: {p.quantity}")
            else:
                print("    holdings: none")
        except Exception as e:  # noqa: BLE001
            print(f"\n[1] get_account FAILED: {e}")
            print("    -> key invalid, wrong secret, or no read permission.")
            return

        # 2) ZERO-RISK order validation (POST /api/v3/order/test).
        native = broker.to_native_symbol(symbol)
        price = await broker._mark_price(native)
        if price is None:
            print(f"\n[2] could not fetch {native} price; skipping order/test.")
            return
        filters = await broker._symbol_filters(native)
        min_notional = filters.get("min_notional") or Decimal("10")
        # Limit price far BELOW market so it could never fill even if it were
        # real (order/test never places it regardless).
        limit_price = await broker._round_price(native, price * Decimal("0.5"))
        # Size just above the venue minimum notional at that price.
        raw_qty = (min_notional * Decimal("1.2")) / limit_price
        qty = await broker._round_qty(native, raw_qty)
        step = filters.get("step") or Decimal("0")
        if step and qty < step:
            qty = step
        params = {
            "symbol": native,
            "side": "BUY",
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": format(qty.normalize(), "f"),
            "price": format(limit_price.normalize(), "f"),
        }
        print(
            f"\n[2] order/test (NO order placed): {native} BUY LIMIT "
            f"{params['quantity']} @ {params['price']}"
        )
        try:
            await broker._signed("POST", "/api/v3/order/test", params)
            print("    order/test OK -> SPOT TRADING permission + filters valid.")
            print("    >> The key is LIVE and ready to trade real money.")
        except Exception as e:  # noqa: BLE001
            print(f"    order/test FAILED: {e}")
            print("    -> usually: trading not enabled on the key, or IP not allowlisted.")
    finally:
        await broker.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
