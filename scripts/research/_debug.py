import asyncio, time
from packages.data.db import get_engine
from packages.livetrade.bars import load_bars
from scripts.research.crypto_search import EmaTrend, Donchian, _metrics
async def main():
    eng = get_engine()
    for res in ["4h"]:
        df = await load_bars(eng, "BTC-USDT@BINANCEUS", res)
        print(res, "bars", len(df), flush=True)
        t=time.time()
        s = EmaTrend(symbols=["BTC-USDT@BINANCEUS"], params=EmaTrend.PARAMS_MODEL(fast=20,slow=50,trend=200,atr_mult=3.0))
        m = _metrics({"BTC-USDT@BINANCEUS": df}, s)
        print(res, "EmaTrend", m, f"{time.time()-t:.1f}s", flush=True)
asyncio.run(main())
