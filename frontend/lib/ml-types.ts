import type { SignalEdgeModel } from "@/lib/backtest-types";

// A trained cross-backtest model is the per-run SignalEdgeModel shape plus the
// feature vocabulary it was trained over.
export interface TrainedModel extends SignalEdgeModel {
  feature_vocabulary: string[];
}

export interface StrategyStats {
  strategy_name: string;
  n_samples: number;
  n_backtests: number;
  n_profitable: number;
  base_profit_rate: number | null;
  model_trained_at: string | null;
  model_n_samples: number | null;
  has_model: boolean;
}

export interface TrainResult {
  strategy_name: string;
  model_id: string;
  n_samples: number;
  n_backtests: number;
  model: TrainedModel;
}

export interface LatestModel {
  id: string;
  strategy_name: string;
  trained_at: string;
  n_samples: number;
  n_backtests: number;
  model: TrainedModel;
}
