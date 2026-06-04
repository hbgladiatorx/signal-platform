// ML API — cross-backtest signal-edge models.
// Wired to the FastAPI /ml router. Models are trained per strategy over the
// accumulated per-trip feature store (see packages/ml in the backend).
import { api } from "@/lib/api/client";

export interface MlStrategyStats {
  strategy_name: string;
  n_samples: number;
  n_backtests: number;
  n_profitable: number;
  base_profit_rate: number | null;
  model_trained_at: string | null;
  model_n_samples: number | null;
  has_model: boolean;
}

// The model payload is the backend's model_to_dict — feature weights and
// per-signal edge. Kept loose; the UI reads known keys defensively.
export interface MlModelPayload {
  fitted?: boolean;
  n_samples?: number;
  feature_weights?: Record<string, number>;
  signal_edge?: Record<
    string,
    { empirical_edge?: number; predicted_edge?: number; n?: number }
  >;
  [k: string]: unknown;
}

export interface MlLatestModel {
  id: string;
  strategy_name: string;
  trained_at: string;
  n_samples: number;
  n_backtests: number;
  model: MlModelPayload;
}

export interface MlTrainResult {
  strategy_name: string;
  model_id: string;
  n_samples: number;
  n_backtests: number;
  model: MlModelPayload;
}

export const getMlStrategies = () =>
  api.get<MlStrategyStats[]>("/ml/strategies");

export const trainMlModel = (name: string) =>
  api.post<MlTrainResult>(`/ml/strategies/${encodeURIComponent(name)}/train`);

export async function getMlModel(name: string): Promise<MlLatestModel | null> {
  const { ApiError } = await import("@/lib/api/client");
  try {
    return await api.get<MlLatestModel>(
      `/ml/strategies/${encodeURIComponent(name)}/model`,
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}
