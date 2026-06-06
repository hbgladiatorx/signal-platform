# Signal Platform — Beginner's Companion

A plain-English explanation of **what every part means**, written for someone
brand new to trading *and* to this kind of software. No jargon left unexplained.

> Read this alongside the **User Guide**. The User Guide tells you *where to
> click*; this document explains *what the words mean and why they matter*.

> **⚠️ Important:** This platform can place real trades with real money. Trading
> is risky and you can lose everything you put in. Nothing here is financial
> advice. Practice with **paper trading** (fake money) until you genuinely
> understand what you're doing.

---

## Part A — Market basics (start here if trading is new to you)

### What is "trading"?
Trading means **buying** something hoping to sell it later for more, or
**selling** something you expect to drop. On this platform the "somethings" are
**cryptocurrencies** (like Bitcoin) and **US stocks** (like Apple).

- **Buy** = you now own it; you profit if the price goes up.
- **Sell** = you give it up for cash; if you sold something you owned, you've
  locked in whatever gain or loss happened while you held it.

### What is an "instrument"?
An **instrument** is just "a specific thing you can trade." Bitcoin priced in US
dollars is one instrument. Apple stock is another. The platform keeps a list of
all the instruments it knows about (the **instrument catalog**).

### Reading a symbol name (the "canonical symbol")
Every instrument has a standard name in the format **`BASE-QUOTE@VENUE`**:

- **BASE** — what you're buying (e.g. `BTC` = Bitcoin, `AAPL` = Apple).
- **QUOTE** — what you're pricing it in (e.g. `USDT` = a US-dollar stablecoin,
  `USD` = US dollars).
- **VENUE** — where it trades / where the data comes from (`BINANCEUS` for
  crypto, `POLYGON` for stocks).

**Examples:**
- `BTC-USDT@BINANCEUS` = "Bitcoin, priced in USDT, on Binance.US."
- `AAPL-USD@POLYGON` = "Apple stock, priced in US dollars, data from Polygon."

You'll see these names everywhere. Once you can read them, the app makes sense.

### Crypto vs. stocks (and "venues")
- **Crypto** trades 24/7 and is accessed here through **Binance.US**, a
  cryptocurrency exchange. The platform can load **every** coin pair Binance.US
  offers.
- **Stocks** trade during US market hours and are accessed through **Polygon.io**,
  a market-data provider for equities.
- A **venue** is simply the source/marketplace. Different venues, same app.

### What is a "candle" / OHLCV / "bar"?
Price charts are drawn with **candles** (also called **bars**). Each candle
summarizes one slice of time with five numbers — **OHLCV**:

- **O**pen — price at the start of the slice
- **H**igh — highest price during the slice
- **L**ow — lowest price during the slice
- **C**lose — price at the end of the slice
- **V**olume — how much was traded during the slice

### What is "resolution"?
**Resolution** is how long each candle covers. The platform supports
**1m, 5m, 15m, 1h, 4h, 1d** (minutes, hours, day). A "1h" chart has one candle
per hour. Shorter resolution = more detail but more noise; longer = smoother,
big-picture.

### Bid, ask, spread, and "quote"
At any moment there's:
- a **bid** — the highest price a buyer will pay right now,
- an **ask** — the lowest price a seller will accept right now,
- the **spread** — the gap between them (a cost of trading; smaller is better),
- a **quote** — a snapshot of the current bid and ask.

### Orders: market vs. limit
An **order** is an instruction to buy or sell. Two main kinds:
- **Market order** — "do it now at whatever the current price is." Fast, but you
  don't control the exact price.
- **Limit order** — "only do it at my price or better." You control the price,
  but it might never fill if the market doesn't reach it.

### Fees and slippage (the hidden costs)
- **Fee** — what the venue charges per trade (often a small percentage). Measured
  in **basis points (bps)**: 1 bp = 0.01%. So "10 bps" = 0.10%.
- **Slippage** — the difference between the price you *expected* and the price you
  *actually got*, because the market moved or your order was large. Backtests let
  you assume a slippage amount so results are realistic, not fantasy.

---

## Part B — The platform's building blocks

### Strategy
A **strategy** is the set of rules that decides when to buy and sell — your
trading idea, written down so a computer can follow it exactly. Example in plain
words: *"Buy when the 10-day average price crosses above the 30-day average; sell
when it crosses back below."*

- **Built-in strategies** ship with the platform (ready to use).
- **Your strategies** are ones you create. You can write them **in plain
  English** and the platform turns them into runnable rules. You can edit or
  **delete** your own (built-ins can't be deleted — they're part of the app).
- **Parameters** are the dials on a strategy (e.g. "10-day" and "30-day" above).
  Changing them changes behavior without rewriting the idea.

### Backtest
A **backtest** runs your strategy over **past** price history to see how it
*would* have done. You pick a strategy, its parameters, which instrument(s), the
resolution, a starting cash amount, and fee/slippage assumptions. The platform
then simulates every trade and reports the results.

**What the result numbers mean:**

| Metric | Plain-English meaning |
|---|---|
| **Total return** | How much the account grew or shrank overall, in %. |
| **Equity curve** | A line chart of your account value over time. Smooth and up = good; jagged = bumpy ride. |
| **Max drawdown** | The worst peak-to-valley drop along the way. "How much pain would I have endured?" Smaller is better. |
| **Sharpe ratio** | Return earned per unit of "bumpiness." Higher = better reward for the risk. Above ~1 is decent. |
| **Sortino ratio** | Like Sharpe but only penalizes *downside* swings. |
| **Win rate** | The % of trades that made money. (High win rate isn't everything — see profit factor.) |
| **Profit factor** | Total winnings ÷ total losses. Above 1 means winners outweigh losers. |
| **Closed trades** | The list of completed round-trips (buy then sell), each with its profit/loss and fees. |

### Overfitting (why a beautiful backtest can lie)
**Overfitting** is when a strategy looks amazing on past data only because it was
accidentally tuned to that exact history — like memorizing the answers to last
year's exam. It then fails on new data. A backtest that looks *too* perfect is a
red flag, not a trophy.

### Walk-forward analysis (the honesty check)
**Walk-forward** is a tougher, more honest test that fights overfitting:

1. Take a chunk of history, **find the best parameters** on it (the "training"
   window).
2. Then test those parameters on the **next** chunk the strategy has **never
   seen** (the "test" window).
3. Slide forward and repeat.

**Analogy:** instead of grading yourself on practice questions you've already
seen, you study, then sit a *fresh* exam — over and over. A strategy that holds
up across many fresh windows is far more trustworthy.

### Paper trading
**Paper trading** = trading with **fake money** against **real, live prices**. It
behaves like the real thing — you place orders, hold positions, see profit and
loss — but nothing real is bought or sold. This is the safe way to forward-test a
strategy and to learn the app. **Always start here.**

### Live trading (and the safety switch)
**Live trading** places **real orders with real money** on Binance.US. Because
this is genuinely risky, it's protected:

- It only works if the system is **explicitly switched on** for live trading
  (off by default).
- It requires your **real exchange API keys**.
- If either is missing, a "live" order is safely **rejected** and never sent.

> Treat the jump from paper to live with respect. Start with small amounts.

### API keys (and how they're protected)
An **API key** is like a special password that lets the platform talk to an
outside service on your behalf — Binance.US (to trade) or Polygon.io (to get
stock data). You add them in **Settings**.

- They are **encrypted** before being stored, and the app **never shows them back
  to you** — only the last few characters, so you can tell which is which.
- For Binance, use **trade-enabled** keys only if you intend to trade live; for
  read-only research you can restrict them.

### The instrument catalog & "active"
The catalog is the master list of tradable symbols. Two useful actions:
- **Add / sync** — bring symbols into the catalog (e.g. import the whole
  Binance.US universe, or specific Polygon tickers).
- **Active vs. inactive** — "active" symbols are the ones the platform
  **streams live data for**. You wouldn't stream thousands at once, so you mark
  just the handful you care about as active.

### Data ingestion & "freshness"
**Ingestion** is the background process that continuously pulls live prices into
the platform. **Freshness** means "how recently did we get data for this symbol?"
The **System Health** screen shows whether ingestion is running and data is
current — important, because a strategy acting on stale data is dangerous.

### Backfilling history
Before you can backtest a symbol, the platform needs its **past** prices stored.
**Backfilling** fetches that history (e.g. a year of Apple's minute bars) and
loads it so backtests have something to run on.

---

## Part C — Every screen, in beginner terms

| Screen | What it's for | What a beginner does here |
|---|---|---|
| **Dashboard** | Your home overview with live activity. | Get oriented; see prices moving. |
| **Instruments** | The catalog of tradable symbols + charts. | Find a symbol, open its chart, mark it active. |
| **Strategies** | Your trading ideas (built-in + yours). | Read a built-in, or create one in plain English. Delete your own if unwanted. |
| **Backtests** | Test a strategy on history. | Run one, then read the equity curve and metrics. |
| **Walk-forwards** | The honesty check on a strategy. | Validate a promising strategy before trusting it. |
| **Settings** | Profile, API keys, data sources. | Add API keys; set your timezone/theme. |
| **System Health** | Is data flowing? | Glance here if charts look stale. |

---

## Part D — Quick glossary (A–Z)

| Term | Quick definition |
|---|---|
| **API key** | A secret password letting the app use an outside service for you. |
| **Ask** | Lowest price a seller will accept right now. |
| **Backtest** | Simulating a strategy on past data. |
| **Backfill** | Loading historical prices so backtests can run. |
| **Bar / Candle** | One time-slice of price (Open/High/Low/Close/Volume). |
| **Basis point (bp)** | 0.01%. 100 bps = 1%. |
| **Bid** | Highest price a buyer will pay right now. |
| **Canonical symbol** | The standard name `BASE-QUOTE@VENUE`. |
| **Drawdown** | A drop from a peak; "max drawdown" is the worst one. |
| **Equity curve** | Your account value plotted over time. |
| **Fee** | What the venue charges per trade. |
| **Instrument** | A specific tradable thing. |
| **Limit order** | Buy/sell only at your price or better. |
| **Live trading** | Real orders, real money. |
| **Market order** | Buy/sell immediately at the going price. |
| **Overfitting** | A strategy tuned to the past that fails on new data. |
| **Paper trading** | Fake-money trading on real prices. |
| **Parameter** | A tunable dial on a strategy. |
| **Resolution** | How long each candle covers (1m…1d). |
| **Sharpe ratio** | Reward earned per unit of bumpiness. |
| **Slippage** | Difference between expected and actual fill price. |
| **Spread** | Gap between bid and ask. |
| **Strategy** | The rules for when to buy and sell. |
| **Venue** | The marketplace/data source (Binance.US, Polygon). |
| **Walk-forward** | Repeated test on unseen data to fight overfitting. |
| **Win rate** | % of trades that made money. |

---

## Part E — Safety & good habits

1. **Start with paper trading.** Always. Learn the app and your strategy with
   fake money first.
2. **Be suspicious of perfect backtests.** If it looks too good, it probably is.
   Run a **walk-forward** before believing it.
3. **Use realistic fees and slippage** in backtests, or your results are fiction.
4. **Go live small.** When you finally do, risk an amount you'd be fine losing.
5. **Protect your keys.** Only enable trade permissions when you truly need them;
   never share keys.
6. **Watch System Health.** Don't trade on stale data.
7. **Remember the disclaimer:** past performance does not predict the future, and
   you can lose your entire investment.

---

*This companion explains concepts in everyday language and is not financial
advice. Trading cryptocurrencies and equities carries substantial risk.*
