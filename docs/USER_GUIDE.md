# Signal Platform — User Guide

A practical, plain-English "how to" for what the site and app do, and how to use
every part of it.

> **What this is.** Signal Platform is a multi-asset quantitative research and
> trading system. You research trading ideas on historical data (backtesting),
> validate them (walk-forward analysis), and then run them with simulated money
> (paper trading) or real money (live trading). It covers **crypto** (Binance.US,
> full spot universe) and **US equities** (via Polygon.io).

> **⚠️ Risk.** This software can place automated trades, including with real
> money. Crypto and equities trading carry substantial risk, up to total loss.
> Backtested or simulated results do **not** predict future performance. Live
> trading is disabled by default and must be deliberately turned on (see
> "Live trading" below). Read this whole guide before trading real capital.

---

## 1. The big picture

The platform is built around a few core ideas. Understanding these makes every
screen obvious.

| Concept | What it means |
|---|---|
| **Instrument** | A tradable thing (e.g. Bitcoin vs USDT, or Apple stock). |
| **Canonical symbol** | The platform's universal name for an instrument: `BASE-QUOTE@VENUE`. Examples: `BTC-USDT@BINANCEUS`, `AAPL-USD@POLYGON`. |
| **Venue** | Where an instrument trades / where its data comes from: `BINANCEUS` (crypto) or `POLYGON` (equities). |
| **Bars (OHLCV)** | Price candles at a resolution (1m, 5m, 15m, 1h, 4h, 1d) — the raw material for charts and backtests. |
| **Strategy** | The trading logic. Either **built-in** (ships with the platform) or **your own** (authored in plain English, compiled to code). |
| **Backtest** | Run a strategy over historical bars to see how it *would* have performed. |
| **Walk-forward** | A tougher test: repeatedly optimize on one window, then test on the *next* unseen window, to reduce over-fitting. |
| **Paper trading** | Live-style trading with **simulated** money. No real orders. |
| **Live trading** | Real orders sent to the venue with real money (Binance.US). Gated behind a safety switch. |

**How data flows (under the hood):** ingestion workers stream live trades/quotes
from Binance.US and Polygon → a message bus → they're stored in a time-series
database → the API serves charts, backtests, and the live websocket → the
Next.js web app shows it all.

---

## 2. Logging in

1. Open the site (e.g. `https://signal.cimcha.com`).
2. You'll be asked to sign in — authentication is handled by **Auth0**.
3. After login you land on the **Dashboard**. Your identity is provisioned
   automatically on first sign-in; your settings and data are scoped to you.

Everything below requires being signed in.

---

## 3. The screens (web app)

The left **sidebar** navigates between sections. Here's what each does.

### Dashboard (`/dashboard`)
Your home base. A live overview — recent market activity and quick links into
the rest of the app. Live prices/trades update in real time via websocket.

### Instruments (`/instruments`)
The catalog of tradable symbols the platform knows about.
- **Browse & filter** by venue (Binance.US / Polygon) and asset class.
- **Click any instrument** (`/instruments/[symbol]`) to see its detail page with
  a **price chart** (switch resolutions: 1m → 1d) and recent **live trades**.
- **Add an instrument** — verifies the symbol exists on the venue before adding.
- **Activate / deactivate** — "active" instruments are the ones the platform
  streams live data for. (Adding the whole Binance universe doesn't auto-stream
  hundreds of pairs; you activate the ones you care about.)

### Strategies (`/strategies`)
The list of strategies you can backtest or trade.
- Each card shows the strategy name, a **"built-in"** or **"yours"** badge, a
  description, and its tunable **parameters**.
- **+ New strategy** (`/strategies/new`) — describe a strategy in **plain
  English**; the platform translates it into a runnable strategy (an LLM-assisted
  translator generates the code and parameter schema).
- **Backtest this →** jumps straight to a new backtest pre-filled with that
  strategy.
- **Delete** *(new)* — on your own strategies only, a Delete button with an
  inline "are you sure?" confirm. Built-in strategies are part of the platform
  and can't be deleted.

### Backtests (`/backtests`)
Run a strategy over history and measure it.
- **New backtest** (`/backtests/new`): pick a strategy, set its parameters,
  choose one or more symbols, a bar resolution, starting cash, and fee/slippage
  assumptions, then submit. It runs in the background.
- The **list** shows each run's status (pending → running → completed/failed) and
  headline metrics: total return, Sharpe, max drawdown, win rate.
- **Open a run** (`/backtests/[id]`) for the full report: summary metrics, the
  **equity curve**, and the list of **closed trades** (entry/exit, P&L, fees).
- **Sweep** (`/backtests/sweep`): run a batch across parameter combinations to
  compare results.

### Walk-forwards (`/walkforwards`)
A more rigorous validation than a single backtest.
- **New walk-forward** (`/walkforwards/new`): choose a strategy, a **parameter
  grid** to search, symbols, resolution, and the train/test window sizes plus
  number of windows.
- It repeatedly **optimizes on a training window**, then evaluates the best
  parameters on the **next unseen test window**, rolling forward. This shows how
  the strategy holds up out-of-sample.
- **Open a run** (`/walkforwards/[id]`) to see per-window results and aggregate
  performance.

### Settings (`/settings`)
Your account and integration configuration, in sections:
- **Profile** — timezone, theme, notification preferences.
- **API Keys** — store exchange/data credentials (Binance.US, Alpaca,
  Polygon.io). Secrets are **encrypted at rest** and never shown back to you;
  only a last-4 summary is displayed. You can add and delete credentials here.
- **Data Sources** — toggle which sources are active.
- **Instruments** — manage your tracked set.

### System Health (`/system/health`)
Operational dashboard — the status of ingestion workers and data freshness, so
you can see whether live data is flowing.

---

## 4. Capabilities added recently (API / CLI today)

These shipped in the latest update. The engines and APIs are complete; some don't
have a dedicated web screen yet, so today you drive them via the API (or CLI).

### Full Binance.US universe
Instead of a hand-picked few pairs, the platform can load **every TRADING spot
pair** on Binance.US.
- **Import the whole catalog:** `POST /instruments/sync/binanceus`
  (optionally filter by quote asset, e.g. only `USDT`/`USD`/`USDC`), or run the
  CLI: `python -m packages.adapters.crypto.binance_universe_sync --quote USDT,USD,USDC --activate`.
- After syncing, any of those pairs can be charted, backtested, paper-traded, or
  live-traded — they're first-class instruments.

### Polygon.io (US equities)
A dedicated data API for stocks, under `/polygon`:
- `GET /polygon/status` — connectivity + market open/closed.
- `GET /polygon/tickers` — search the equity universe.
- `GET /polygon/aggregates` — historical OHLC bars for a ticker.
- `GET /polygon/last-trade`, `GET /polygon/last-quote` — latest prints.
- `POST /polygon/sync-universe` — import Polygon tickers into your instrument
  catalog as equities (`AAPL-USD@POLYGON`, etc.).
- **Backfill for backtesting:**
  `python -m packages.backtest.polygon_backfill --symbol AAPL-USD@POLYGON --start 2024-01-01 --end 2025-01-01`
  pulls history so equities backtest exactly like crypto.
- Requires a `POLYGON_API_KEY` set in the server environment. (Live streaming and
  intraday history depend on your Polygon plan tier.)

### Paper & live trading
A full execution layer, under `/trading`:
- **Create an account** (`POST /trading/accounts`) in either **paper** or **live**
  mode, with a starting balance and fee/slippage assumptions.
- **Place orders** (`POST /trading/orders`): market or limit, buy or sell, over
  any instrument in your catalog (the full Binance universe).
- **Manage**: list/cancel orders, view positions and balances per account.
- **Paper mode** fills against the latest known price in a simulated account —
  safe, no real money, good for forward-testing a strategy live.
- **Live mode** sends real signed orders to Binance.US.

> **Live trading safety switch.** Live orders only transmit when the server has
> `BINANCEUS_LIVE_TRADING_ENABLED=true` **and** valid Binance.US credentials.
> Without that flag, any live order is safely recorded as "rejected" and never
> reaches the exchange. Paper trading always works regardless.

---

## 5. End-to-end: a typical workflow

1. **Get instruments.** Sync the Binance universe (`/instruments/sync/binanceus`)
   and/or Polygon tickers (`/polygon/sync-universe`), then **activate** the
   symbols you want on the Instruments page.
2. **(Equities only) Backfill history** with the Polygon backfill command so
   there's data to test on. Crypto history can be backfilled similarly.
3. **Create or pick a strategy** on the Strategies page (write one in plain
   English, or use a built-in).
4. **Backtest it** (`/backtests/new`) over your chosen symbols and period. Review
   the equity curve, drawdown, and trades.
5. **Walk-forward validate** (`/walkforwards/new`) to check it holds up
   out-of-sample. Be skeptical of strategies that look great in backtest but fall
   apart here.
6. **Paper trade** it: create a paper account and place orders (or run the
   strategy against it) to watch it behave on live data with fake money.
7. **Go live (optional, carefully).** Add real Binance.US API keys in Settings,
   have an admin flip the live switch on the server, create a **live** account,
   and start small.

---

## 6. Quick reference: key API endpoints

| Area | Endpoint |
|---|---|
| Market bars | `GET /market/bars?symbol=BTC-USDT@BINANCEUS&resolution=1h` |
| Latest quote | `GET /market/quote/latest?symbol=...` |
| Instruments | `GET/POST /instruments`, `PUT /instruments/{symbol}/active` |
| Sync Binance universe | `POST /instruments/sync/binanceus` |
| Strategies | `GET /strategies`, `POST/PUT/DELETE /user-strategies/{id}` |
| Backtests | `POST /backtests`, `GET /backtests/{id}` (+ `/trades`, `/equity`) |
| Walk-forwards | `POST /walkforwards`, `GET /walkforwards/{id}` |
| Trading | `POST /trading/accounts`, `POST /trading/orders`, `GET /trading/status` |
| Polygon | `GET /polygon/{status,tickers,aggregates,last-trade,last-quote}` |
| Settings / keys | `GET/POST/DELETE /settings/api-keys` |

All endpoints require a valid signed-in session (bearer token).

---

## 7. Troubleshooting

- **"Polygon is not configured" (503)** → `POLYGON_API_KEY` isn't set on the
  server. Add it to the deployment's `.env` and restart.
- **A symbol can't be backtested** → it has no history yet. Backfill it first.
- **No live data on a symbol** → it isn't *active* on the Instruments page, or the
  ingestion worker isn't running (check System Health).
- **Live order was "rejected" immediately** → the live safety switch is off, or no
  Binance.US credentials are configured. This is expected, protective behavior.
- **A backtest is stuck "pending"** → the background worker may be down; check that
  the backtest worker service is running.

---

*This guide describes the platform's behavior. Features without a dedicated web
screen (full-universe sync, Polygon, paper/live trading) are operated via the API
or CLI today and may gain UI screens in future updates.*
