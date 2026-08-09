"""The graph is the source of truth for what a strategy runs on.

A compiled strategy's runnable `source_code` does NOT bake in its symbol or
timeframe: `on_init` binds `self.symbol = self.symbols[0]` from whatever symbol
list is passed at run time, and the bar resolution is chosen by the caller. So
the symbol and timeframe the user wired into the graph's price (data) node must
be read *back* from the persisted graph and made authoritative for every run.
Otherwise the canvas and the execution silently disagree — a run inherits the
previous backtest's symbol/resolution instead of what the user actually drew.

This module is the single extractor both run paths (the copilot's
`_tool_run_backtest` and the HTTP `POST /backtests`) use, so the two can never
diverge in how they read intent out of the graph.
"""
from __future__ import annotations

from typing import Any, Optional

# Bar resolutions a run can execute at (mirrors livetrade.bars.RESOLUTION_TABLE
# and copilot's accepted set).
VALID_BAR_RESOLUTIONS = {"1m", "5m", "15m", "1h", "4h", "1d"}


def _data_nodes(graph: Optional[dict[str, Any]]):
    """Yield the graph's price / options-chain / data-category nodes, in order.

    These are the nodes that carry the symbol + timeframe the user picked. We
    accept `type == "price"`, `type == "optionsChain"`, or `category == "data"`
    so the extractor is robust to the builder's node taxonomy.
    """
    if not graph:
        return
    for node in graph.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") in ("price", "optionsChain") or node.get("category") == "data":
            yield node


def graph_symbol(graph: Optional[dict[str, Any]]) -> Optional[str]:
    """The symbol the user wired into the graph's data node — authoritative for
    the run. Returns the symbol string as stored (canonical, e.g. ``SPY@ALPACA``)
    or None if the graph has no data node with a symbol (e.g. raw-code strategies
    that were never built from a graph).
    """
    for node in _data_nodes(graph):
        sym = ((node.get("data") or {}).get("symbol") or "").strip()
        if sym:
            return sym
    return None


def graph_bar_resolution(graph: Optional[dict[str, Any]]) -> Optional[str]:
    """The timeframe the user set on the graph's data node — authoritative for
    the run. Returns a valid bar resolution, or None if the graph has no usable
    one. Reading this is what makes "switch to 5m" actually take effect instead
    of the run inheriting the previous backtest's resolution.
    """
    for node in _data_nodes(graph):
        tf = ((node.get("data") or {}).get("timeframe") or "").strip().lower()
        if tf in VALID_BAR_RESOLUTIONS:
            return tf
    return None
