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
}

export interface WalkforwardDetail extends WalkforwardSummary {
  starting_cash: number | string;
  fee_rate_bps: number;
  slippage_bps: number;
  param_grid: Record<string, unknown[]>;
  train_bars: number;
  test_bars: number;
  windows?: unknown[];
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
