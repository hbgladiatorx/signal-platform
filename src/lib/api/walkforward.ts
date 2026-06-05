// Walk-forward analysis API.
// Wired to the FastAPI /walkforwards router. A walk-forward runs a rolling
// train/test parameter sweep, reporting out-of-sample (test) performance per
// window — the honest measure of whether a strategy's edge holds up.
import { api } from "@/lib/api/client";

export interface WalkforwardSummary {
  id: string;
  strategy_name: string;
  symbols: string[];
  bar_resolution: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  num_windows: number;
  total_combos: number | null;
  avg_test_sharpe: number | null;
  avg_test_return_pct?: number | null;
  win_rate_windows_pct?: number | null;
  error_message?: string | null;
}

export interface WalkforwardWindow {
  window_index: number;
  train_start_ts: string;
  train_end_ts: string;
  test_start_ts: string;
  test_end_ts: string;
  best_params: Record<string, unknown>;
  train_sharpe: number | null;
  train_total_return_pct: number | null;
  train_max_drawdown_pct: number | null;
  train_num_closed_trades: number;
  test_sharpe: number | null;
  test_total_return_pct: number | null;
  test_max_drawdown_pct: number | null;
  test_num_closed_trades: number;
}

export interface WalkforwardDetail extends WalkforwardSummary {
  starting_cash: number | string;
  fee_rate_bps: number;
  slippage_bps: number;
  param_grid: Record<string, unknown[]>;
  train_bars: number;
  test_bars: number;
  windows_result?: WalkforwardWindow[] | null;
  avg_train_sharpe?: number | null;
  overfit_drop?: number | null;
  [k: string]: unknown;
}

export interface CreateWalkforwardInput {
  strategy_name: string;
  symbols: string[];
  bar_resolution: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
  starting_cash?: number;
  fee_rate_bps?: number;
  slippage_bps?: number;
  param_grid: Record<string, unknown[]>;
  train_bars: number;
  test_bars: number;
  num_windows: number;
  selection_metric?: "sharpe" | "sortino" | "total_return" | "calmar";
}

export const listWalkforwards = () =>
  api.get<WalkforwardSummary[]>("/walkforwards");

export const getWalkforward = (id: string) =>
  api.get<WalkforwardDetail>(`/walkforwards/${id}`);

export const createWalkforward = (body: CreateWalkforwardInput) =>
  api.post<{ id: string; status: string }>("/walkforwards", body);
