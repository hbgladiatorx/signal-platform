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
  stats?: StrategyStats;
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
