"""Bayn Copilot — the pipeline-driving agent.

The existing AI Builder (packages.strategy.llm_translator / graph_planner) only
wires the node graph. This package extends that into a single agent that drives
the whole strategy lifecycle from one chat box: build -> backtest -> validate
(OOS) -> forward test -> promote -> deploy -> submit.

Modules:
  state  — the canonical lifecycle stage machine + gates + get_strategy_state
  tools  — the Anthropic tool schemas + server-side dispatch to real endpoints
  prompt — the verbatim system prompt + stage->call-to-action map
  agent  — the tool-use loop that ties it together
"""
