# Signal Platform

Multi-asset quantitative research and trading platform.

**Asset coverage:** Crypto (Binance.US) in Phase 1; Options (Alpaca) in Phase 4.
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
| packages/adapters/ | Asset-class-specific adapters (crypto, options) |
| services/api/ | FastAPI gateway |
| services/ingestion_*/ | Per-source ingestion workers |
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

## Risk Notice

This system enables automated trading of cryptocurrencies and (later) options.
Both carry substantial risk including total capital loss. Backtested or
simulated performance is not indicative of future results. See
infra/runbooks/RISK_NOTICE.md before deploying real capital.
