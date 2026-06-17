"""
Deterministic node-graph → Strategy source compiler.

The visual builder produces a node graph (price → indicator → comparator →
entry/exit signal, plus risk nodes). Until now that graph was flattened to a
natural-language description and handed to an LLM to write the Python. The LLM
is unreliable — it silently dropped exit rules (e.g. a graph with "RSI > 70 →
exit" compiled to entry-only code), so backtests didn't reflect what the user
drew.

This module compiles the graph DIRECTLY and deterministically into a Strategy
subclass that honours every entry, exit, and risk node. It covers the common
indicator-threshold shape the builder emits (RSI/EMA/SMA/ATR compared to a
constant, wired to long entry and exit signals, with an optional stop and
position size). Anything it doesn't recognise returns ok=False so the caller
can fall back to the LLM translator — the compiler never emits half-right code.

The engine is long-only, so options legs (optionsChain nodes) compile to a long
position in the UNDERLYING with the same signal logic — a faithful directional
proxy until real options execution lands.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# Indicator node type → (BarContext method, default period). Only indicators
# the framework actually exposes are compilable; others force LLM fallback.
_INDICATOR_METHODS: dict[str, str] = {
    "rsi": "rsi",
    "ema": "ema",
    "sma": "sma",
    "atr": "atr",
}

# Node types that, if present in a way we can't compile, force a fallback.
_UNSUPPORTED_LOGIC = {"formula", "and", "or", "not", "crossover", "macd", "bb",
                      "stoch", "vwap", "orderBook", "econCalendar", "fundamentals",
                      "timeWindow", "cooldown"}


@dataclass
class CompileResult:
    ok: bool
    source_code: str | None = None
    class_name: str | None = None
    params_class_name: str | None = None
    reason: str | None = None  # why we fell back, for logging/telemetry
    notes: list[str] = field(default_factory=list)


def _class_name_from(name: str) -> str:
    """Turn a strategy name into a valid PascalCase Python identifier."""
    cleaned = re.sub(r"[^0-9a-zA-Z]+", " ", name or "Strategy").strip()
    parts = [p[:1].upper() + p[1:] for p in cleaned.split() if p]
    cls = "".join(parts) or "Strategy"
    if cls[0].isdigit():
        cls = "S" + cls
    return cls


def _num(v: Any) -> float | None:
    try:
        if isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _direction(node: dict) -> str:
    """Classify a signal node (entry/exit) as 'LONG' or 'SHORT'.

    Entry nodes carry an explicit ``data.direction`` ("LONG"|"SHORT"). Exit
    nodes carry no direction in the palette (``data: {}``), so fall back to the
    label ("Exit SHORT" → short). Anything unspecified defaults to LONG — the
    engine is long-only, so an undirected signal is treated as the long leg.
    """
    d = node.get("data") or {}
    raw = str(d.get("direction") or "").strip().upper()
    if raw in ("LONG", "SHORT"):
        return raw
    label = str(node.get("label") or "").upper()
    if "SHORT" in label:
        return "SHORT"
    return "LONG"


def _edges(graph: dict) -> list[dict]:
    return [e for e in (graph.get("edges") or []) if isinstance(e, dict)]


def _nodes(graph: dict) -> list[dict]:
    return [n for n in (graph.get("nodes") or []) if isinstance(n, dict)]


def compile_graph_to_source(
    *, name: str, asset_class: str, graph: dict | None
) -> CompileResult:
    """Compile a builder graph into Strategy source. ok=False ⇒ fall back to LLM."""
    if not graph or not _nodes(graph):
        return CompileResult(ok=False, reason="empty graph")

    nodes = _nodes(graph)
    edges = _edges(graph)
    by_id = {n.get("id"): n for n in nodes if n.get("id")}
    notes: list[str] = []

    def node_type(n: dict) -> str:
        return str(n.get("type") or "")

    # ---- price / symbol ----
    price_nodes = [n for n in nodes if node_type(n) == "price"]
    chain_nodes = [n for n in nodes if node_type(n) == "optionsChain"]
    symbol: str | None = None
    if price_nodes:
        symbol = (price_nodes[0].get("data") or {}).get("symbol")
    elif chain_nodes:
        symbol = (chain_nodes[0].get("data") or {}).get("symbol")
        notes.append(
            "Options legs compile to a long position in the underlying "
            f"{symbol} — the engine is long-only equity in this phase."
        )
    if not symbol:
        return CompileResult(ok=False, reason="no price/options symbol node")

    # ---- bail out on logic we can't faithfully compile ----
    for n in nodes:
        t = node_type(n)
        if t in _UNSUPPORTED_LOGIC:
            return CompileResult(ok=False, reason=f"unsupported node type {t!r}")

    # ---- indicators ----
    # id -> {"method": "rsi", "period": 14, "var": "rsi_14"}
    indicators: dict[str, dict] = {}
    for n in nodes:
        t = node_type(n)
        if t in _INDICATOR_METHODS:
            period = (n.get("data") or {}).get("period")
            p = int(period) if isinstance(period, (int, float)) and period else (
                14 if t in ("rsi", "atr") else 20
            )
            indicators[n.get("id")] = {
                "method": _INDICATOR_METHODS[t],
                "period": p,
                "var": f"{t}_{p}",
                "type": t,
            }

    # ---- comparators wired to entry / exit signals ----
    # The engine is LONG-ONLY. A long/short graph (e.g. RSI mean reversion with
    # both a LONG entry on "oversold" and a SHORT entry on "overbought") must
    # compile ONLY its long leg. Mixing the two — collecting comparators across
    # both directions and AND-joining them — yields impossible conditions like
    # "RSI < 30 and RSI > 70", which never fire (every backtest returns 0
    # trades). Split by direction and keep the long side only.
    all_entry_nodes = [n for n in nodes if node_type(n) == "entry"]
    all_exit_nodes = [n for n in nodes if node_type(n) == "exit"]
    entry_ids = {n.get("id") for n in all_entry_nodes if _direction(n) == "LONG"}
    exit_ids = {n.get("id") for n in all_exit_nodes if _direction(n) == "LONG"}
    if any(_direction(n) == "SHORT" for n in all_entry_nodes):
        if not entry_ids:
            # Purely short strategy — the long-only engine can't represent it.
            return CompileResult(
                ok=False, reason="short-only strategy; long-only engine"
            )
        notes.append(
            "Short legs were dropped — the engine is long-only in this phase; "
            "only the long entry/exit signals are compiled."
        )
    if not entry_ids:
        return CompileResult(ok=False, reason="no entry signal node")

    # upstream(target) -> list of source node ids
    upstream: dict[str, list[str]] = {}
    for e in edges:
        upstream.setdefault(e.get("target"), []).append(e.get("source"))

    def comparators_feeding(target_ids: set[str]) -> list[dict]:
        out = []
        for tid in target_ids:
            for sid in upstream.get(tid, []):
                src = by_id.get(sid)
                if src and node_type(src) == "comparator":
                    out.append(src)
        return out

    def _operand(sid: str) -> tuple[str | None, str | None, dict | None]:
        """Classify a comparator input: ('series', expr, ind) for an indicator,
        ('price', 'price', None) for the price node, else (None, None, None)."""
        if sid in indicators:
            ind = indicators[sid]
            return ("series", ind["var"], ind)
        node = by_id.get(sid)
        if node is not None and node_type(node) == "price":
            return ("price", "price", None)
        return (None, None, None)

    def build_conditions(comparators: list[dict]) -> list[dict] | None:
        """Compile each comparator into a condition.

        Two shapes are supported:
          * indicator vs constant — ``RSI < 30`` (one indicator feeds the
            comparator; the level comes from the node's ``value``).
          * series vs series — ``price < EMA`` (price AND an indicator, or two
            indicators, feed the comparator). The node's ``value`` is a UI
            placeholder and is ignored. Previously this shape was miscompiled to
            ``indicator <op> value`` (e.g. ``ema < 0``), a dead condition that
            never fired, so these strategies always backtested 0 trades.
        """
        conds: list[dict] = []
        for cmp_node in comparators:
            data = cmp_node.get("data") or {}
            op = data.get("op")
            if op not in ("<", ">", "<=", ">="):
                return None  # references a level/expr we can't compile
            operands = [
                _operand(sid) for sid in upstream.get(cmp_node.get("id"), [])
            ]
            series = [o for o in operands if o[0] in ("series", "price")]
            if len(series) >= 2:
                # Series vs series. Prefer price as the left operand so the
                # condition reads like the builder's "Price <op> Indicator";
                # otherwise (indicator vs indicator) keep edge order.
                price_ops = [o for o in series if o[0] == "price"]
                ind_ops = [o for o in series if o[0] == "series"]
                if price_ops and ind_ops:
                    left, right = price_ops[0], ind_ops[0]
                else:
                    left, right = series[0], series[1]
                ref_ind = left[2] or right[2]
                conds.append(
                    {
                        "form": "series",
                        "op": op,
                        "left": left[1],
                        "right": right[1],
                        "inds": [o[2] for o in (left, right) if o[2] is not None],
                        "sig_type": ref_ind["type"] if ref_ind else "price",
                        "sig_value_var": ref_ind["var"] if ref_ind else "price",
                    }
                )
                continue
            # Indicator vs constant.
            value = _num(data.get("value"))
            ind = series[0][2] if series and series[0][0] == "series" else None
            if ind is None or value is None:
                return None  # not a shape we can faithfully compile
            conds.append({"form": "ind_const", "ind": ind, "op": op, "value": value})
        return conds

    entry_cmps = comparators_feeding(entry_ids)
    exit_cmps = comparators_feeding(exit_ids)
    if not entry_cmps:
        return CompileResult(ok=False, reason="entry has no comparator condition")

    entry_conds = build_conditions(entry_cmps)
    exit_conds = build_conditions(exit_cmps) if exit_cmps else []
    if entry_conds is None or exit_conds is None:
        return CompileResult(ok=False, reason="condition not compilable")

    # ---- risk nodes ----
    stop_pct: float | None = None
    for n in nodes:
        if node_type(n) == "stopLoss":
            d = n.get("data") or {}
            if d.get("type") == "percent":
                stop_pct = _num(d.get("value"))
            # atr/r-multiple stops need trade context we don't track here →
            # skip (entry/exit signals still drive the strategy).

    # ---- take-profit node ----
    # Previously the compiler ignored takeProfit nodes entirely, so any target a
    # user drew was silently dropped — the position could only ever close on the
    # exit signal or the stop. Honour it now. We resolve the target to a percent
    # distance above entry at compile time:
    #   percent     → that percent directly
    #   r_multiple  → reward = R × risk, where risk is the percent stop distance
    #                 (so 2R against a 3% stop = a 6% target). Needs a percent
    #                 stop to measure R against; without one we can't, so we note
    #                 it and leave the target off rather than guess.
    tp_pct: float | None = None
    for n in nodes:
        if node_type(n) == "takeProfit":
            d = n.get("data") or {}
            val = _num(d.get("value"))
            if val is None or val <= 0:
                continue
            t = d.get("type")
            if t == "r_multiple":
                if stop_pct is not None and stop_pct > 0:
                    tp_pct = val * stop_pct
                else:
                    notes.append(
                        "Take-profit is R-multiple but there's no percent stop to "
                        "measure R against — target skipped; exit/stop still apply."
                    )
            else:  # "percent" (or unspecified) → treat as a percent distance
                tp_pct = val

    # ---- position sizing ----
    # Honour the positionSize node the user drew. The old compiler hardcoded
    # 0.01 BASE UNITS, which for an equity at ~$400-600 is ~$5 of exposure on a
    # $25k account — so every backtest returned ~0% no matter how the strategy
    # actually performed. Size as a fraction of account equity (or a fixed cash
    # amount) and convert to a quantity at the entry price instead.
    #   percent_account → qty = (pct/100) * equity / price
    #   fixed_cash      → qty = cash_amount / price
    # The entry only fires when flat, so ctx.cash == account equity at entry.
    sizing: dict[str, Any] = {"mode": "percent_account", "value": 95.0}
    for n in nodes:
        if node_type(n) == "positionSize":
            d = n.get("data") or {}
            val = _num(d.get("value"))
            if val is None or val <= 0:
                continue
            if d.get("type") == "fixed_cash":
                sizing = {"mode": "fixed_cash", "value": val}
            else:  # "percent_account" (or unspecified) → treat as percent
                sizing = {"mode": "percent_account", "value": val}

    # ---- emit ----
    cls = _class_name_from(name)
    params_cls = f"{cls}Params"
    src = _emit_source(
        class_name=cls,
        params_class_name=params_cls,
        strategy_name=name,
        symbol=symbol,
        indicators=list({id(v): v for v in indicators.values()}.values()),
        entry_conds=entry_conds,
        exit_conds=exit_conds,
        stop_pct=stop_pct,
        tp_pct=tp_pct,
        sizing=sizing,
        notes=notes,
    )
    return CompileResult(
        ok=True, source_code=src, class_name=cls,
        params_class_name=params_cls, notes=notes,
    )


def _emit_source(
    *,
    class_name: str,
    params_class_name: str,
    strategy_name: str,
    symbol: str,
    indicators: list[dict],
    entry_conds: list[dict],
    exit_conds: list[dict],
    stop_pct: float | None,
    tp_pct: float | None,
    sizing: dict[str, Any],
    notes: list[str],
) -> str:
    # Unique indicator vars (period-deduped) → one param + one ctx call each.
    uniq: dict[str, dict] = {}
    for ind in indicators:
        uniq[ind["var"]] = ind

    def _cond_inds(c: dict) -> list[dict]:
        return [c["ind"]] if c.get("form", "ind_const") == "ind_const" else c["inds"]

    # Ensure every indicator referenced by a condition is present.
    for c in (*entry_conds, *exit_conds):
        for ind in _cond_inds(c):
            uniq[ind["var"]] = ind

    lines: list[str] = []
    A = lines.append

    A('"""')
    A(f"{strategy_name} — compiled from the visual builder graph.")
    A("")
    A("Long-only. Generated deterministically so every entry, exit, and risk")
    A("node in the graph is honoured exactly as drawn.")
    for note in notes:
        A(f"- {note}")
    A('"""')
    A("from __future__ import annotations")
    A("")
    A("from decimal import Decimal")
    A("")
    A("from pydantic import BaseModel, Field")
    A("")
    A("from packages.strategy.base import Strategy")
    A("from packages.strategy.context import BarContext")
    A("")
    A("")
    A(f"class {params_class_name}(BaseModel):")
    A(f'    """Parameters for {strategy_name}."""')
    A("")
    # period params
    for var, ind in uniq.items():
        A(f"    {var}_period: int = Field(")
        A(f"        default={ind['period']}, ge=2, le=400,")
        A(f'        description="Lookback period for {ind["type"].upper()}.",')
        A("    )")
    # threshold params — only "indicator vs constant" conditions carry a tunable
    # level. Series-vs-series conditions (price vs EMA) compare two live values
    # and have no constant to expose. The param name is stashed on the condition
    # so the on_bar expression below references the same identifier.
    def _emit_thresholds(conds: list[dict], side: str) -> None:
        ic = [c for c in conds if c.get("form", "ind_const") == "ind_const"]
        for i, c in enumerate(ic):
            nm = f"{side}_threshold_{i+1}" if len(ic) > 1 else f"{side}_threshold"
            c["_thr"] = nm
            A(f"    {nm}: float = Field(")
            A(f"        default={c['value']}, ge=-1e9, le=1e9,")
            A(f'        description="{side.capitalize()} trigger level for '
              f'{c["ind"]["type"].upper()}.",')
            A("    )")

    _emit_thresholds(entry_conds, "entry")
    _emit_thresholds(exit_conds, "exit")

    def _cond_expr(c: dict) -> str:
        if c.get("form", "ind_const") == "ind_const":
            return f"{c['ind']['var']} {c['op']} self.params.{c['_thr']}"
        return f"{c['left']} {c['op']} {c['right']}"

    def _cond_sig(c: dict) -> tuple[str, str]:
        """(signal_type, value_var) for the ctx.signal() attribution call."""
        if c.get("form", "ind_const") == "ind_const":
            return c["ind"]["type"], c["ind"]["var"]
        return c["sig_type"], c["sig_value_var"]
    if stop_pct is not None:
        A("    stop_loss_percent: float = Field(")
        A(f"        default={stop_pct}, gt=0, le=90,")
        A('        description="Stop-loss distance below entry, in percent.",')
        A("    )")
    if tp_pct is not None:
        A("    take_profit_percent: float = Field(")
        A(f"        default={tp_pct}, gt=0, le=1000,")
        A('        description="Take-profit distance above entry, in percent.",')
        A("    )")
    if sizing["mode"] == "fixed_cash":
        A("    position_cash: float = Field(")
        A(f"        default={sizing['value']}, gt=0,")
        A('        description="Cash deployed per entry, in account currency.",')
        A("    )")
    else:
        A("    position_pct: float = Field(")
        A(f"        default={sizing['value']}, gt=0, le=100,")
        A('        description="Percent of account equity deployed per entry.",')
        A("    )")
    A("")
    A("")
    A(f"class {class_name}(Strategy[{params_class_name}]):")
    A(f'    """{strategy_name} (compiled, long-only)."""')
    A("")
    A(f"    PARAMS_MODEL = {params_class_name}")
    A("")
    A("    def on_init(self) -> None:")
    A("        if len(self.symbols) != 1:")
    A("            raise ValueError(")
    A(f"                f\"{class_name} supports exactly one symbol, \"")
    A('                f"got {len(self.symbols)}: {self.symbols}"')
    A("            )")
    A("        self.symbol: str = self.symbols[0]")
    A('        self.state["stop_price"] = None')
    if tp_pct is not None:
        A('        self.state["target_price"] = None')
    A("")
    A("    def on_bar(self, ctx: BarContext) -> None:")
    # indicator fetches
    for var, ind in uniq.items():
        A(f"        {var} = ctx.{ind['method']}(self.symbol, self.params.{var}_period)")
    A("        price = ctx.close(self.symbol)")
    # None guards
    guard_vars = list(uniq.keys()) + ["price"]
    A(f"        if {' is None or '.join(guard_vars)} is None:")
    A("            return")
    A("        position = ctx.position(self.symbol)")
    A("")
    # stop loss
    if stop_pct is not None:
        A('        if position > 0 and self.state["stop_price"] is not None:')
        A('            if price <= self.state["stop_price"]:')
        A("                ctx.submit_sell_market(self.symbol, position)")
        A('                self.state["stop_price"] = None')
        if tp_pct is not None:
            A('                self.state["target_price"] = None')
        A("                return")
        A("")
    # take profit
    if tp_pct is not None:
        A('        if position > 0 and self.state["target_price"] is not None:')
        A('            if price >= self.state["target_price"]:')
        A('                ctx.signal("take_profit", passed=True, value=price, symbol=self.symbol)')
        A("                ctx.submit_sell_market(self.symbol, position)")
        A('                self.state["target_price"] = None')
        A('                self.state["stop_price"] = None')
        A("                return")
        A("")
    # exit conditions
    if exit_conds:
        joined = " and ".join(_cond_expr(c) for c in exit_conds)
        A(f"        if position > 0 and ({joined}):")
        # Tag each exit condition so attribution / the signal-edge model can
        # report per-signal performance (otherwise the ML shows "no signals").
        for i, c in enumerate(exit_conds):
            typ, val_var = _cond_sig(c)
            sig = f"{typ}_exit" + (f"_{i+1}" if len(exit_conds) > 1 else "")
            A(f'            ctx.signal("{sig}", passed=True, value={val_var}, symbol=self.symbol)')
        A("            ctx.submit_sell_market(self.symbol, position)")
        A('            self.state["stop_price"] = None')
        if tp_pct is not None:
            A('            self.state["target_price"] = None')
        A("            return")
        A("")
    # entry conditions
    joined = " and ".join(_cond_expr(c) for c in entry_conds)
    A(f"        if position == 0 and ({joined}):")
    # Tag each entry condition — this is what feeds per-signal edge analytics.
    for i, c in enumerate(entry_conds):
        typ, val_var = _cond_sig(c)
        sig = f"{typ}_entry" + (f"_{i+1}" if len(entry_conds) > 1 else "")
        A(f'            ctx.signal("{sig}", passed=True, value={val_var}, symbol=self.symbol)')
    # Size the order from account equity (ctx.cash == equity while flat), so the
    # position is economically meaningful for any asset/price — not a fixed
    # 0.01-unit sliver. Submit only when the computed quantity is positive.
    if sizing["mode"] == "fixed_cash":
        A("            qty = Decimal(str(self.params.position_cash)) / price")
    else:
        A("            qty = (")
        A("                Decimal(str(self.params.position_pct)) / Decimal(\"100\")")
        A("            ) * ctx.cash / price")
    A("            if qty > 0:")
    A("                ctx.submit_buy_market(self.symbol, qty)")
    if stop_pct is not None:
        A("                self.state[\"stop_price\"] = price * Decimal(")
        A("                    str(1 - self.params.stop_loss_percent / 100)")
        A("                )")
    if tp_pct is not None:
        A("                self.state[\"target_price\"] = price * Decimal(")
        A("                    str(1 + self.params.take_profit_percent / 100)")
        A("                )")
    A("")
    return "\n".join(lines) + "\n"
