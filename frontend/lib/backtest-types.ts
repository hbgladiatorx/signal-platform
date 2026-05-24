/**
 * Types for the Strategies and Backtests API surface.
 *
 * These mirror the Pydantic response models in:
 *   services/api/routers/strategies.py
 *   services/api/routers/backtests.py
 *
 * Decimal values arrive as JSON numbers (or strings for very large ones —
 * Postgres NUMERIC can serialize either way). We type them as `number`
 * here; consumers should call Number(x) defensively if needed.
 */

// ============================================================
// Strategies
// ============================================================

export interface StrategyParamSchema {
  type: "integer" | "number" | "string" | "boolean";
  title?: string;
  description?: string;
  default?: number | string | boolean;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
}

export interface StrategyJsonSchema {
  title?: string;
  description?: string;
  type: "object";
  properties: Record<string, StrategyParamSchema>;
  required?: string[];
}

export interface Strategy {
  name: string;
  description: string;
  params_schema: StrategyJsonSchema;
}

// ============================================================
// Backtests
// ============================================================

export type BacktestStatus = "pending" | "running" | "completed" | "failed";

export type BarResolution = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";

export const BAR_RESOLUTIONS: BarResolution[] = [
  "1m",
  "5m",
  "15m",
  "1h",
  "4h",
  "1d",
];

export interface BacktestSummary {
  id: string;
  strategy_name: string;
  symbols: string[];
  bar_resolution: string;
  status: BacktestStatus;
  created_at: string;
  completed_at?: string | null;
  duration_seconds?: number | null;
  total_return_pct?: number | null;
  sharpe_ratio?: number | null;
  max_drawdown_pct?: number | null;
  num_closed_trades?: number | null;
  win_rate_pct?: number | null;
  bars_start?: string | null;
  bars_end?: string | null;
  num_bars?: number | null;
}

export interface BacktestDetail {
  id: string;
  strategy_name: string;
  params_json: Record<string, unknown>;
  symbols: string[];
  bar_resolution: string;
  bars_start?: string | null;
  bars_end?: string | null;
  num_bars?: number | null;
  starting_cash: number | string;
  fee_rate_bps: number;
  slippage_bps: number;
  status: BacktestStatus;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  total_return_pct?: number | null;
  annualized_return_pct?: number | null;
  sharpe_ratio?: number | null;
  sortino_ratio?: number | null;
  max_drawdown_pct?: number | null;
  calmar_ratio?: number | null;
  num_closed_trades?: number | null;
  num_open_trades?: number | null;
  win_rate_pct?: number | null;
  profit_factor?: number | null;
}

export interface BacktestTrade {
  symbol: string;
  side: string;
  entry_ts: string;
  exit_ts: string;
  entry_avg_price: number | string;
  exit_avg_price: number | string;
  quantity: number | string;
  gross_pnl: number | string;
  fees: number | string;
  net_pnl: number | string;
  duration_seconds: number;
  num_fills: number;
}

export interface BacktestEquityPoint {
  ts: string;
  cash: number | string;
  positions_value: number | string;
  total_equity: number | string;
}

export interface CreateBacktestRequest {
  strategy_name: string;
  params: Record<string, unknown>;
  symbols: string[];
  bar_resolution: BarResolution;
  starting_cash: number | string;
  fee_rate_bps?: number;
  slippage_bps?: number;
}

export interface CreateBacktestResponse {
  id: string;
  status: BacktestStatus;
}
