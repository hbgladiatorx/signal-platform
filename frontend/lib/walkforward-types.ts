// frontend/lib/walkforward-types.ts
// TypeScript types and formatters for walk-forward analysis.
//
// Matches the Pydantic shapes in services/api/routers/walkforwards.py and the
// WindowResult / WalkforwardResult dataclasses in packages/backtest/walkforward.py.

export type WalkforwardStatus = "pending" | "running" | "completed" | "failed";

export type SelectionMetric = "sharpe" | "sortino" | "total_return" | "calmar";

export interface WindowResult {
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

export interface WalkforwardSummary {
  id: string;
  strategy_name: string;
  symbols: string[];
  bar_resolution: string;
  status: WalkforwardStatus;
  created_at: string;
  num_windows: number;
  total_combos: number | null;
  total_backtests_run: number | null;
  duration_seconds: number | null;
  avg_train_sharpe: number | null;
  avg_test_sharpe: number | null;
  avg_test_return_pct: number | null;
  overfit_drop: number | null;
  win_rate_windows_pct: number | null;
}

export interface WalkforwardDetail extends WalkforwardSummary {
  starting_cash: string;
  fee_rate_bps: number;
  slippage_bps: number;
  train_bars: number;
  test_bars: number;
  selection_metric: SelectionMetric;
  param_grid: Record<string, unknown[]>;
  windows_result: WindowResult[] | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface CreateWalkforwardRequest {
  strategy_name: string;
  symbols: string[];
  bar_resolution: string;
  starting_cash: number;
  fee_rate_bps: number;
  slippage_bps: number;
  param_grid: Record<string, unknown[]>;
  train_bars: number;
  test_bars: number;
  num_windows: number;
  selection_metric: SelectionMetric;
}

// ============================================================
// Formatters
// ============================================================
export function fmtSharpe(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(2);
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}%`;
}

export function fmtNum(
  v: number | null | undefined,
  digits = 0,
): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds))
    return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

export function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ============================================================
// Status + overfit visualization
// ============================================================
export function statusColor(status: WalkforwardStatus): string {
  switch (status) {
    case "completed":
      return "bg-emerald-100 text-emerald-800 border-emerald-200";
    case "running":
      return "bg-blue-100 text-blue-800 border-blue-200";
    case "pending":
      return "bg-gray-100 text-gray-700 border-gray-200";
    case "failed":
      return "bg-red-100 text-red-800 border-red-200";
  }
}

export interface OverfitBadge {
  label: string;
  color: string;
  description: string;
}

/** Severity buckets for the Sharpe drop from train to test.
 *
 * Following Pardo (2008) convention loosely:
 *   - > 2.0 Sharpe drop: severe
 *   - 1.0 to 2.0: high
 *   - 0.5 to 1.0: moderate
 *   - 0 to 0.5: low
 *   - ≤ 0 (test ≥ train): none
 */
export function overfitBadge(
  overfit_drop: number | null | undefined,
): OverfitBadge {
  if (
    overfit_drop === null ||
    overfit_drop === undefined ||
    Number.isNaN(overfit_drop)
  ) {
    return {
      label: "—",
      color: "bg-gray-100 text-gray-700 border-gray-200",
      description: "Not computable (insufficient data or null Sharpe)",
    };
  }
  if (overfit_drop > 2.0) {
    return {
      label: "Severe",
      color: "bg-red-100 text-red-800 border-red-200",
      description:
        "Sharpe collapse > 2.0 from train to test. Strong evidence of overfitting.",
    };
  }
  if (overfit_drop > 1.0) {
    return {
      label: "High",
      color: "bg-amber-100 text-amber-800 border-amber-200",
      description:
        "Sharpe drop > 1.0 from train to test. Likely overfitting.",
    };
  }
  if (overfit_drop > 0.5) {
    return {
      label: "Moderate",
      color: "bg-yellow-100 text-yellow-800 border-yellow-200",
      description: "Sharpe drop 0.5–1.0. Some overfitting suspected.",
    };
  }
  if (overfit_drop > 0) {
    return {
      label: "Low",
      color: "bg-emerald-100 text-emerald-800 border-emerald-200",
      description: "Sharpe drop < 0.5. Reasonable generalization.",
    };
  }
  return {
    label: "None",
    color: "bg-emerald-100 text-emerald-800 border-emerald-200",
    description:
      "Test ≥ train Sharpe. No overfitting evidence in this sample.",
  };
}

export const SELECTION_METRICS: {
  value: SelectionMetric;
  label: string;
  description: string;
}[] = [
  {
    value: "sharpe",
    label: "Sharpe Ratio",
    description: "Annualized risk-adjusted return. Most common selection metric.",
  },
  {
    value: "sortino",
    label: "Sortino Ratio",
    description: "Like Sharpe but only penalizes downside volatility.",
  },
  {
    value: "total_return",
    label: "Total Return %",
    description: "Highest absolute return; ignores risk and drawdown.",
  },
  {
    value: "calmar",
    label: "Calmar Ratio",
    description: "Annualized return ÷ |max drawdown|. Penalizes deep drawdowns.",
  },
];

export const BAR_RESOLUTIONS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
