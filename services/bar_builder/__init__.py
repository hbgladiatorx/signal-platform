"""Live bar-builder service.

Subscribes to trades:raw and constructs OHLCV bars at six resolutions
(1m, 5m, 15m, 1h, 4h, 1d) in memory. Publishes:
  - bars:live    — throttled snapshots of in-progress bars
  - bars:closed  — emitted once per bar at bucket boundary

See main.py for full documentation.
"""
