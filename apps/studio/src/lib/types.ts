export type AssetClass = "stocks" | "crypto" | "options" | "futures";
export type Direction = "LONG" | "SHORT";
export type SignalStatus = "OPEN" | "HIT_TARGET" | "HIT_STOP" | "EXPIRED";
export type StrategyStatus = "Watching" | "In Position" | "Cooldown";
export type PipelineStage =
  | "Draft"
  | "Backtested"
  | "Out-of-Sample Passed"
  | "Forward Testing"
  | "Live"
  | "Submitted"
  | "Under Review"
  | "Published"
  | "Rejected";

export interface StrategyStats {
  sharpe: number;
  winRate: number;
  maxDrawdown: number;
  sampleSize: number;
  avgR: number;
  liveDays: number;
  subscribers: number;
  // Headline backtest summary surfaced in the studio strategy list/detail.
  totalReturn?: number; // fraction (0.123 = +12.3%)
  profitFactor?: number;
  totalTrades?: number;
}

export interface Strategy {
  id: string;
  name: string;
  description: string;
  longDescription: string;
  entryRules: string;
  exitRules: string;
  assetClass: AssetClass;
  devHandle: string;
  status: StrategyStatus;
  stage: PipelineStage;
  edgeVerified: boolean;
  symbols: string[];
  lastSignalAt: string;
  stats: StrategyStats;
  createdAt: string;
}

export interface Signal {
  id: string;
  strategyId: string;
  strategyName: string;
  assetClass: AssetClass;
  symbol: string;
  direction: Direction;
  entry: number;
  stop: number;
  target: number;
  status: SignalStatus;
  firedAt: string;
  closedAt?: string;
  pnlR?: number;
  reasoning: string;
  strike?: number;
  expiry?: string;
  delta?: number;
  iv?: number;
  contractMonth?: string;
  tickSize?: number;
  priceSeries: Array<{ t: string; price: number }>;
}

export interface MarketTile {
  symbol: string;
  label: string;
  assetClass: AssetClass | "index";
  price: number;
  changePct: number;
  spark: number[];
}

export interface EquityPoint { t: string; equity: number; }

export interface TakenSignal {
  id: string;
  signalId: string;
  signal: Signal;
  takenAt: string;
  fillPrice: number;
  pnlR?: number;
  outcome: SignalStatus;
}

/* ---------- Studio (developer-side) types ---------- */

export type NodeCategory = "data" | "indicator" | "logic" | "risk" | "signal";

export interface StrategyNode {
  id: string;
  type: string;            // e.g. "price", "sma", "comparator", "stopLoss", "entry"
  category: NodeCategory;
  label: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
}

export interface StrategyEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
}

export interface StrategyGraph {
  nodes: StrategyNode[];
  edges: StrategyEdge[];
}

export interface DevStrategy {
  id: string;
  name: string;
  description: string;
  assetClass: AssetClass;
  stage: PipelineStage;
  createdAt: string;
  lastRunAt?: string;
  graph: StrategyGraph;
  sourceCode?: string;
  stats?: StrategyStats;
  isActive?: boolean;
  liveSinceDays?: number;
  versions: Array<{ id: string; createdAt: string; note: string }>;
  submissionStatus?: "Submitted" | "Under Review" | "Pipeline Validation" | "Human Review" | "Accepted" | "Rejected";
  submissionNotes?: string;
}

export interface BacktestRun {
  id: string;
  strategyId: string;
  ranAt: string;
  params: { startDate: string; endDate: string; capital: number; commissionBps: number; slippageBps: number };
  stats: {
    totalReturn: number;
    cagr: number;
    sharpe: number;
    sortino: number;
    maxDrawdown: number;
    winRate: number;
    profitFactor: number;
    avgWin: number;
    avgLoss: number;
    avgHoldDays: number;
    totalTrades: number;
  };
  equity: EquityPoint[];
  trades: Array<{
    id: string;
    entryDate: string;
    exitDate: string;
    symbol: string;
    direction: Direction;
    entry: number;
    exit: number;
    pnlPct: number;
    pnlR: number;
  }>;
  monthlyReturns: Array<{ month: string; ret: number }>;
  // The instruments + bar resolution this run actually used — carried so a
  // re-run (out-of-sample, AI-tweaked) reuses the same universe, not a re-resolve.
  symbols?: string[];
  barResolution?: string;
  // Backend "why" layers (optional; present on full detail fetches).
  attribution?: BacktestAttribution | null;
  mlModel?: BacktestMlModel | null;
  analysis?: BacktestAnalysis | null;
}

// ---- Performance attribution (packages/backtest/attribution.py) ----
// Money fields arrive as strings (Decimal) — coerce with Number() for display.
export interface AttributionSymbol {
  symbol: string;
  num_trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
  gross_pnl: string;
  fees: string;
  net_pnl: string;
  avg_net_pnl: string;
  pct_of_total_net_pnl: number | null;
}
export interface AttributionSignal {
  name: string;
  num_fired: number;
  num_blocked: number;
  num_evaluated: number;
  block_rate_pct: number | null;
  num_trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
  net_pnl: string;
  avg_net_pnl: string;
  pct_of_total_net_pnl: number | null;
}
export interface BacktestAttribution {
  total_net_pnl: string;
  num_closed_trades: number;
  by_symbol: AttributionSymbol[];
  by_signal: AttributionSignal[];
  untagged_trades: number;
  untagged_net_pnl: string;
  best_symbol: string | null;
  worst_symbol: string | null;
  best_signal: string | null;
  worst_signal: string | null;
}

// ---- Signal-edge ML model (packages/ml/model.py model_to_dict) ----
export interface MlSignalEdge {
  name: string;
  num_trades: number;
  empirical_profit_rate: number;
  mean_predicted_prob: number;
  lift_vs_base_pp: number;
}
export interface MlFeatureWeight {
  feature: string;
  weight: number;
}
export interface BacktestMlModel {
  n_samples: number;
  n_features: number;
  base_profit_rate: number | null;
  fitted: boolean;
  reason: string | null;
  train_accuracy: number | null;
  train_log_loss: number | null;
  feature_weights: MlFeatureWeight[];
  signal_edges: MlSignalEdge[];
  count_feature?: string;
}

// ---- AI parameter tweaks (packages/analysis/tweak_advisor.py) ----
// A node-targeted suggested change the user can edit and re-backtest.
export interface ParamTweak {
  node_id: string;
  node_label?: string | null;
  node_type?: string | null;
  field: string;
  current: string | number | boolean | null;
  suggested: string | number | boolean;
  rationale: string;
}
export interface SuggestTweaksResult {
  ok: boolean;
  summary: string;
  tweaks: ParamTweak[];
  error?: string | null;
}

// ---- Deterministic analysis (packages/analysis/backtest_analysis.py) ----
export type AnalysisSeverity = "good" | "warn" | "bad" | "info";
export interface AnalysisFinding {
  id: string;
  kind: string;
  severity: AnalysisSeverity;
  title: string;
  detail: string;
  suggestion: string;
}
export interface BacktestAnalysis {
  schema: number;
  verdict: "profitable" | "marginal" | "unprofitable" | "inconclusive";
  headline: string;
  score: number;
  metrics: {
    profit_factor: number | null;
    sharpe: number | null;
    sortino: number | null;
    win_rate_pct: number | null;
    breakeven_win_pct: number | null;
    payoff_ratio: number | null;
    expectancy_pct: number | null;
    max_drawdown_pct: number | null;
    total_return_pct: number | null;
    num_closed_trades: number;
  };
  findings: AnalysisFinding[];
  narrative: string | null;
}

export interface PersonalSignal extends Signal {
  ownStrategyId: string;
  ownStrategyName: string;
}

export interface StudioEarning {
  month: string;
  strategyId: string;
  strategyName: string;
  amount: number;
  subscribers: number;
}
