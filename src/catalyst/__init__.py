"""Asymmetric Catalyst Breakout Signal & Backtest System.

Two products, one codebase (Section 0):
  * a daily live signal engine (Modules 1-5), and
  * a point-in-time backtester (Module 6),
both routed through the Module 0 point-in-time data layer.

The non-negotiable property of this package is POINT-IN-TIME INTEGRITY: every
historical decision uses only data knowable as of its decision date. See
``catalyst.pit`` and ``catalyst.store.panel`` for the hard enforcement, and
``tests/`` for the assertions that prove it.
"""

__version__ = "0.1.0"
