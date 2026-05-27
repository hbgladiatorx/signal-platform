export type AssetClass = "stocks" | "crypto" | "options" | "futures";
export type Direction = "LONG" | "SHORT";
export type SignalStatus = "OPEN" | "HIT_TARGET" | "HIT_STOP" | "EXPIRED";
export type StrategyStatus = "Watching" | "In Position" | "Cooldown";
export type PipelineStage =
  | "Draft"
  | "Backtested"
  | "Out-of-Sample Passed"
  | "Forward Testing"
  | "Submitted"
  | "Published"
  | "Rejected";

export interface StrategyStats {
  sharpe: number;
  winRate: number;       // 0..1
  maxDrawdown: number;   // 0..1
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
  lastSignalAt: string;     // ISO
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
  // option/future extras
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
