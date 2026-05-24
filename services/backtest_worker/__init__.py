"""Backtest worker service.

Consumes backtest job UUIDs from the Redis LIST `backtest:jobs` and
executes each by:
  1. Loading the backtest header from DB
  2. Marking it 'running'
  3. Loading bars from the appropriate cagg table
  4. Discovering and instantiating the strategy
  5. Running the backtest
  6. Computing analytics
  7. Persisting results

See main.py for full documentation.
"""
