// Bayn Copilot client. The copilot is one chat box that drives the whole
// build → backtest → validate (OOS) → forward lifecycle. Unlike chatStudioAI
// (which only returns a node graph for the canvas), the copilot runs tools
// server-side: it builds + saves strategies, runs backtests/OOS/forward, and
// returns a fresh `state` object that drives the pipeline stepper and chips.
//
// History is owned here on the client: we send the full message list each turn
// (POST /copilot/chat). The backend is stateless between turns.
import { api } from "@/lib/api/client";

export const COPILOT_STAGES = [
  "draft",
  "backtested",
  "oos_passed",
  "forward",
  "deployable",
  "bayn_eligible",
] as const;

export type CopilotStage = (typeof COPILOT_STAGES)[number];

export interface CopilotGates {
  backtest_completed: boolean;
  enough_trades: boolean;
  profitable_backtest: boolean;
  oos_passed: boolean;
  forward_started: boolean;
  promoted: boolean;
  deployed_live: boolean;
  submitted_to_bayn: boolean;
}

export interface CopilotState {
  strategy_id: string;
  name: string;
  asset_class: string | null;
  stage: CopilotStage;
  stage_index: number;
  latest_backtest_id: string | null;
  latest_backtest_status: string | null;
  trade_count: number | null;
  sharpe: number | null;
  total_return_pct: number | null;
  latest_oos_id: string | null;
  latest_oos_status: string | null;
  avg_test_sharpe: number | null;
  latest_forward_session_id: string | null;
  latest_forward_status: string | null;
  last_deploy_mode: string | null;
  gates_passed: CopilotGates;
  next_action: { action: string; label: string };
}

// One turn of conversation. content is plain text from the UI; the backend also
// accepts structured content but we never need to send it.
export interface CopilotMessage {
  role: "user" | "assistant";
  content: string;
}

export interface CopilotToolCall {
  name: string;
  input: Record<string, unknown>;
  result: Record<string, unknown>;
}

export interface CopilotChatResponse {
  ok: boolean;
  reply: string;
  strategy_id: string | null;
  state: CopilotState | null;
  tool_trace: CopilotToolCall[];
  input_tokens: number;
  output_tokens: number;
  error: string | null;
}

/** Run one assistant turn. Pass the full prior history plus the new user turn. */
export async function sendCopilotChat(
  messages: CopilotMessage[],
  strategyId: string | null,
): Promise<CopilotChatResponse> {
  return api.post<CopilotChatResponse>("/copilot/chat", {
    messages,
    strategy_id: strategyId ?? undefined,
  });
}

/** Fetch lifecycle state directly (first paint + polling running jobs). */
export async function getCopilotState(strategyId: string): Promise<CopilotState> {
  return api.get<CopilotState>(`/copilot/strategies/${strategyId}/state`);
}

// Human-friendly labels for the stepper.
export const STAGE_LABEL: Record<CopilotStage, string> = {
  draft: "Draft",
  backtested: "Backtested",
  oos_passed: "Validated",
  forward: "Forward test",
  deployable: "Ready",
  bayn_eligible: "Live",
};

export const STAGE_BLURB: Record<CopilotStage, string> = {
  draft: "Strategy built — not tested yet.",
  backtested: "Tested on history.",
  oos_passed: "Held up out of sample.",
  forward: "Running on live bars (paper fills).",
  deployable: "Signed off, ready to deploy.",
  bayn_eligible: "Deployed live.",
};

/** Turn a next_action verb into the message that triggers it in chat. */
export function actionToMessage(action: string): string | null {
  switch (action) {
    case "run_backtest":
      return "Run a backtest.";
    case "run_oos_test":
      return "Run the out-of-sample test.";
    case "start_forward_test":
      return "Start a forward test.";
    case "promote_strategy":
      return "Promote this to deployable — I confirm.";
    case "deploy_strategy":
      return "Deploy this to paper.";
    case "submit_to_bayn":
      return "Submit this to the Bayn desk — I confirm.";
    default:
      return null;
  }
}

/** True when a backtest/OOS/forward run is in flight (worth polling). */
export function isWorking(state: CopilotState | null): boolean {
  if (!state) return false;
  const running = new Set(["pending", "running", "starting"]);
  return (
    running.has(state.latest_backtest_status ?? "") ||
    running.has(state.latest_oos_status ?? "")
  );
}
