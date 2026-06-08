"""Pluggable historical bar sources for backtest backfill (Binance.US klines,
Polygon aggregates, ...). Each maps a source's 1-minute bars into the shared
synthetic-trade → continuous-aggregate machinery in
``packages.backtest.historical_backfill``."""
