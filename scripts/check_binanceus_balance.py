"""Read the Binance.US account balance via the shared platform credential, so we
can size live sessions to stay under the $500/order cap (orders over the cap are
rejected, so oversizing means no trades — and we must not oversize real money).
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from packages.data.db import get_sessionmaker
from packages.core.encryption import decrypt_json
from packages.broker.binanceus import BinanceUSBroker

CRED_ID = "2ed6aa67-139e-47e1-9a8a-e480b844d1c0"  # j@msn.com Binance.US (Q7o9)


async def main():
    sm = get_sessionmaker()
    async with sm() as s:
        row = (await s.execute(text(
            "SELECT encrypted_payload FROM api_credentials WHERE id=:id"),
            {"id": CRED_ID})).mappings().first()
    payload = decrypt_json(bytes(row["encrypted_payload"]))
    broker = BinanceUSBroker(api_key=payload["api_key"], secret_key=payload["secret_key"])
    acct = await broker.get_account()
    print(f"cash={acct.cash} equity={acct.equity}")


if __name__ == "__main__":
    asyncio.run(main())
