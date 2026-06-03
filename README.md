# Signal Platform

Multi-asset quantitative research and trading platform.

**Asset coverage:** Crypto — the full Binance.US spot universe; Equities — Polygon.io.
**Execution:** Backtesting, paper trading, and live trading (Binance.US).
**Hosting:** AWS Lightsail at https://signal.cimcha.com
**Status:** Phase 1 — Foundation

## Architecture

See `infra/runbooks/00_architecture.md` for the full architectural overview.

Data flow at a glance:

- Frontend (Next.js)
- API (FastAPI)
- Message Bus (Redis Streams)
- Persistence Worker writes to TimescaleDB
- Ingestion (Binance.US WSS) feeds the Message Bus

## Repository Structure

| Directory | Purpose |
|-----------|---------|
| packages/core/ | Domain models, types, exceptions |
| packages/data/ | Database, message bus, normalizers |
| packages/adapters/ | Asset-class-specific adapters (crypto, equity) |
| packages/execution/ | Paper + live order execution (brokers, routing) |
| services/api/ | FastAPI gateway |
| services/ingestion_*/ | Per-source ingestion workers (Binance.US, Polygon) |
| services/persistence_worker/ | Redis to DB writer |
| frontend/ | Next.js application |
| migrations/ | Alembic database migrations |
| infra/docker/ | Per-service Dockerfiles |
| infra/caddy/ | Reverse proxy configuration |
| infra/scripts/ | Deployment and maintenance scripts |
| infra/runbooks/ | Operational documentation |

## Development Workflow

1. Edit code on your Mac
2. Commit and push to GitHub
3. Pull on the Lightsail box
4. Run docker compose up -d --build to deploy changes

## Environment

Copy .env.example to .env and fill in real values. Never commit .env.

## Phases

- Phase 1 (current): Foundation — data pipeline, auth, UI shell
- Phase 2: Strategy DSL + backtest engine
- Phase 3: Paper trading + risk service
- Phase 4: Options adapter (Alpaca) + news/sentiment
- Phase 5: Shadow + live trading
- Phase 6: ML layer (feature store, training, inference)

## Data Sources & Trading

**Binance.US — full universe.** Symbol translation and the instrument catalog
are driven from Binance.US `exchangeInfo`, not a hardcoded list. Import every
TRADING spot pair with:

```bash
# In-process catalog sync (idempotent):
docker exec -it signal_api python -m packages.adapters.crypto.binance_universe_sync --quote USDT,USD,USDC --activate
# Or over HTTP:
curl -XPOST $API/instruments/sync/binanceus -H "Authorization: Bearer $JWT" \
     -d '{"quote_assets":["USDT","USD","USDC"],"activate":true}'
```

**Polygon.io — equities.** A dedicated `/polygon` API serves aggregate bars,
last trade/quote, ticker search, and catalog sync. Backfill history into the
bar chain (so Polygon symbols backtest like crypto):

```bash
docker exec -it signal_api python -m packages.backtest.polygon_backfill \
    --symbol AAPL-USD@POLYGON --start 2024-01-01 --end 2025-01-01
```

**Paper & live trading.** The `/trading` API creates accounts (`paper` or
`live`), places/cancels orders, and reports positions and balances over the
full instrument universe. Paper orders fill against the latest known price in a
simulated account; live orders are transmitted to Binance.US via signed REST.

> **Live trading is gated.** Real order transmission requires the
> `BINANCEUS_LIVE_TRADING_ENABLED=true` kill-switch env var *and* valid
> Binance.US credentials (a user's encrypted `api_credentials` row, or the
> `BINANCEUS_API_KEY`/`BINANCEUS_API_SECRET` env fallback). Without the flag,
> live orders are persisted as `rejected` and never leave the box. Paper
> trading is always available.

## Risk Notice

This system enables automated trading of cryptocurrencies and (later) options.
Both carry substantial risk including total capital loss. Backtested or
simulated performance is not indicative of future results. See
infra/runbooks/RISK_NOTICE.md before deploying real capital.
