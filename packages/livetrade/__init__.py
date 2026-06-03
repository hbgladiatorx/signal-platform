"""Live (paper) trading runtime.

Shared building blocks for running a strategy live against the bars:closed
stream and routing orders to a broker. Mirrors the backtest package structure
but for the always-on, event-driven world:

  bars.py          — load warm-start history from the cagg tables
  position_math.py — average-cost accounting shared with the backtest portfolio
  persistence.py   — paper_* table CRUD
  session.py       — LiveSession: the per-session on_bar loop
  reconciler.py    — consume broker trade_updates, apply fills, fire callbacks
  router.py        — BarRouter + SessionRegistry: fan bars out to sessions
"""
