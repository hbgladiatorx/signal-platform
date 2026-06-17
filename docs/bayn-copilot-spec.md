# Bayn Copilot — pipeline-driving agent (implemented spec)

One chat box drives the full strategy lifecycle: **build → backtest → validate
(OOS) → forward test → promote → deploy → submit**. The user never has to learn
which tab a step lives in.

This is the *corrected* spec — the original assumed a wiring job over endpoints
that already existed. In reality the lifecycle state machine, the gated
milestones, and the "desk" did not exist and were built here. This document
describes what was actually shipped.

- Model: `claude-sonnet-4-6` (override with `COPILOT_MODEL`). The rest of the
  codebase still runs `claude-sonnet-4-20250514` and is due a bump.
- Entry point: `POST /copilot/chat`. State source of truth:
  `GET /copilot/strategies/{id}/state`.

---

## The pipeline (and how each stage is decided)

```
draft → backtested → oos_passed → forward → deployable → bayn_eligible
```

Stages are **hybrid**: the early ones are derived from real artifacts so they
can't drift; the gated ones are stored milestones set only by a confirmed action.

| Stage | How it's reached | Source |
|---|---|---|
| `draft` | strategy created | default |
| `backtested` | ≥1 **completed** backtest exists | derived |
| `oos_passed` | ≥1 completed walk-forward with `avg_test_sharpe > 0` | derived |
| `forward` | ≥1 paper session exists for the strategy | derived |
| `deployable` | `promoted_at` set (confirmed promotion) | stored milestone |
| `bayn_eligible` | `deployed_live_at` set (confirmed **live** deploy) | stored milestone |

Derivation + gates live in `packages/copilot/state.py`. Artifacts are linked to a
strategy by `strategy_name`, scoped to the owning user.

### Gates (`gates_passed`)
`backtest_completed`, `enough_trades` (≥30 closed trades),
`profitable_backtest`, `oos_passed`, `forward_started`, `promoted`,
`deployed_live`, `submitted_to_bayn`. These drive the "what's blocking" line and
the suggested-action chip.

### One map, three consumers
`next_action_for_stage(stage, gates)` returns `{action, label}` — the same value
feeds the chat chips, the pipeline stepper button, and the agent's "what's next"
line. The chat response includes a fresh `state` object so the UI re-renders the
stepper in lock-step after every turn.

---

## Async reality (the spec's biggest correction)

Backtests, OOS, and forward tests run on **background workers** via Redis queues
— results are not synchronous. The tools enqueue, then poll briefly
(`COPILOT_POLL_SECONDS`, default 25s, kept under the 120s gunicorn timeout). If a
run is still going, the tool returns `status: "running"` and the agent says so
rather than inventing a result. `get_backtest_analysis` / `get_strategy_state`
fetch results once a run is `completed`.

---

## Tools → real machinery

| Tool | Backed by | Notes |
|---|---|---|
| `get_strategy_state` | `state.compute_strategy_state` | the aggregator; gates + next action |
| `build_strategy` | `plan_graph_from_nl` → `compile_graph_to_source` → validate → `create_user_strategy` | returns a `draft` strategy_id |
| `edit_strategy_node` | graph refine via planner → recompile → `update_user_strategy` | downstream results marked stale |
| `run_backtest` | `create_backtest` + enqueue + poll | copilot defaults: last 2y, $25k, 5/3 bps; `['UNIVERSE']` → universe_50 |
| `get_backtest_analysis` | `load_backtest` | metrics + attribution + analysis; running→status |
| `run_oos_test` | `create_walkforward` + enqueue + poll | synthesizes param grid + windows from the strategy/last backtest |
| `start_forward_test` | `create_paper_session` (Alpaca paper) | requires `oos_passed` |
| `promote_strategy` | `set_strategy_lifecycle_milestone(promoted)` | requires `user_confirmed` + `forward` |
| `deploy_strategy` | `create_paper_session` (paper/live venue) | live requires `user_confirmed` + a live credential + guardrails |
| `submit_to_bayn` | insert `bayn_submissions` | requires `user_confirmed` + `bayn_eligible` |

Notes on what the original spec got wrong, now handled in the tool layer:
- **No standalone deploy endpoint.** Deploying = starting a trading session; the
  mode (paper vs live) follows the credential's venue (`alpaca` → paper,
  `alpaca_live`/`binanceus` → live). `start_forward_test` and
  `deploy_strategy(paper)` both create paper sessions; the guardrail boundary is
  enforced in the agent/tool layer.
- **OOS is a walk-forward**, not a single held-out slice; the zero-arg call
  synthesizes train/test sizing and a param grid.
- **Backtest defaults** ($25k / 5 / 3 / 2y / UNIVERSE) live in the copilot tool
  layer; the underlying `POST /backtests` keeps its own defaults
  ($10k / 10 / 5 / full history) for every other caller.

---

## Guardrails

- Backtests, OOS, and forward tests run **freely**.
- **Promotion** and **live deploy** require `user_confirmed=true` (the user must
  confirm in their latest message). **Paper deploy** is allowed on request.
- A tool called out of order returns a clear error naming the missing step; the
  agent runs the missing step instead of refusing flatly.

---

## System prompt

Verbatim in `packages/copilot/prompt.py` (`SYSTEM_PROMPT`). It keeps the original
voice — know the next action, translate results into a plain verdict, flag <30
trades, diagnose-and-offer-to-fix on failure, no selling — and adds the truth
about asynchronous runs and what OOS/forward/deploy actually do.

When a `strategy_id` is open on the canvas it's injected into the system context
so "this strategy" resolves without asking the user for an id.

---

## API

### `POST /copilot/chat`
```jsonc
{
  "messages": [{ "role": "user", "content": "How is this strategy doing?" }],
  "strategy_id": "4e5b9ef5-…"        // optional: the strategy open on the canvas
}
```
Response: `{ ok, reply, strategy_id, state, tool_trace, input_tokens, output_tokens, error }`.
History is owned by the frontend — send the full `messages` array each turn.
`state` is the same shape `GET /copilot/strategies/{id}/state` returns; render the
stepper and chips from it.

### `GET /copilot/strategies/{id}/state`
The `get_strategy_state` aggregator as a plain endpoint, for first paint and
polling running jobs.

---

## Files

- `migrations/versions/0019_copilot_lifecycle.sql` — milestone columns + `bayn_submissions`
- `packages/copilot/state.py` — stage machine, gates, aggregator
- `packages/copilot/tools.py` — tool schemas + server-side dispatch
- `packages/copilot/prompt.py` — system prompt + model id
- `packages/copilot/agent.py` — the tool-use loop
- `services/api/routers/copilot.py` — `/copilot/chat` + state endpoint
- `packages/data/user_strategies.py` — milestone setter + state read

## Deploy

Migration 0019 is applied. The api image bakes in code at build time, so rebuild
and recreate the api to serve the new routes:

```bash
cd ~/app
docker compose build api
docker compose up -d --force-recreate api
docker compose logs --tail=30 api
```

Streaming the reply token-by-token (SSE) is a known follow-up — the endpoint
currently returns the assembled reply plus a per-tool trace.
```
