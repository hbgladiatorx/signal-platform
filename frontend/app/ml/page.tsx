"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AppShell } from "@/components/nav/AppShell";
import type { SignalEdge, SignalFeatureWeight } from "@/lib/backtest-types";
import type {
  LatestModel,
  StrategyStats,
  TrainResult,
  TrainedModel,
} from "@/lib/ml-types";
import { useApi } from "@/lib/useApi";


export default function MlModelsPage() {
  const api = useApi();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);

  const statsQuery = useQuery({
    queryKey: ["ml", "strategies"],
    queryFn: () => api.get<StrategyStats[]>("/ml/strategies"),
  });

  // Latest model for the selected strategy (fetched on demand).
  const modelQuery = useQuery({
    queryKey: ["ml", "model", selected],
    queryFn: () => api.get<LatestModel>(`/ml/strategies/${selected}/model`),
    enabled: !!selected,
    retry: false,
  });

  const trainMutation = useMutation({
    mutationFn: (name: string) =>
      api.post<TrainResult>(`/ml/strategies/${name}/train`, {}),
    onSuccess: (res) => {
      setSelected(res.strategy_name);
      qc.invalidateQueries({ queryKey: ["ml", "strategies"] });
      qc.invalidateQueries({ queryKey: ["ml", "model", res.strategy_name] });
    },
  });

  const stats = statsQuery.data ?? [];

  return (
    <AppShell title="ML Models">
      <div className="space-y-4">
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-6 py-3">
            <h2 className="text-sm font-semibold text-navy-700">
              Signal-edge models
            </h2>
            <p className="mt-0.5 text-xs text-gray-500">
              Every completed backtest feeds its closed trades into a per-strategy
              sample store. Train a model over the accumulated trades to learn which
              signals precede winners — across all runs, not just one.
            </p>
          </div>

          {statsQuery.isLoading && (
            <div className="px-6 py-12 text-center text-sm text-gray-500">
              Loading…
            </div>
          )}
          {statsQuery.error && (
            <div className="px-6 py-4 text-sm text-red-600">
              {(statsQuery.error as Error).message}
            </div>
          )}
          {statsQuery.data && stats.length === 0 && (
            <div className="px-6 py-12 text-center text-sm text-gray-500">
              No training data yet. Run a backtest of a signal-emitting strategy
              that produces closed trades, and it will show up here.
            </div>
          )}

          {stats.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-4 py-2 font-medium">Strategy</th>
                    <th className="px-4 py-2 text-right font-medium">Samples</th>
                    <th className="px-4 py-2 text-right font-medium">Backtests</th>
                    <th className="px-4 py-2 text-right font-medium">Win rate</th>
                    <th className="px-4 py-2 font-medium">Model</th>
                    <th className="px-4 py-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {stats.map((s) => (
                    <tr key={s.strategy_name} className="hover:bg-gray-50">
                      <td className="px-4 py-2 font-mono text-xs">{s.strategy_name}</td>
                      <td className="px-4 py-2 text-right font-mono text-xs">
                        {s.n_samples}
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-xs">
                        {s.n_backtests}
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-xs">
                        {s.base_profit_rate != null
                          ? `${(s.base_profit_rate * 100).toFixed(1)}%`
                          : "—"}
                      </td>
                      <td className="px-4 py-2 text-xs text-gray-600">
                        {s.has_model && s.model_trained_at ? (
                          <span title={s.model_trained_at}>
                            {new Date(s.model_trained_at).toLocaleString()}{" "}
                            <span className="text-gray-400">
                              ({s.model_n_samples} samples)
                            </span>
                          </span>
                        ) : (
                          <span className="text-gray-400">not trained</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <div className="flex justify-end gap-2">
                          {s.has_model && (
                            <button
                              type="button"
                              onClick={() => setSelected(s.strategy_name)}
                              className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
                            >
                              View
                            </button>
                          )}
                          <button
                            type="button"
                            disabled={
                              trainMutation.isPending || s.n_samples === 0
                            }
                            onClick={() => trainMutation.mutate(s.strategy_name)}
                            className="rounded bg-navy-600 px-2 py-1 text-xs font-medium text-white hover:bg-navy-700 disabled:opacity-40"
                          >
                            {trainMutation.isPending &&
                            trainMutation.variables === s.strategy_name
                              ? "Training…"
                              : s.has_model
                                ? "Retrain"
                                : "Train"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {trainMutation.error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-3 text-sm text-red-700">
            Training failed: {(trainMutation.error as Error).message}
          </div>
        )}

        {/* Selected model */}
        {selected && (
          <ModelPanel
            strategyName={selected}
            loading={modelQuery.isLoading}
            error={modelQuery.error as Error | null}
            data={modelQuery.data}
          />
        )}
      </div>
    </AppShell>
  );
}


function ModelPanel({
  strategyName,
  loading,
  error,
  data,
}: {
  strategyName: string;
  loading: boolean;
  error: Error | null;
  data: LatestModel | undefined;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-6 py-3">
        <h3 className="font-mono text-sm font-semibold text-navy-700">
          {strategyName}
        </h3>
        <p className="mt-0.5 text-xs text-gray-500">
          Latest cross-backtest signal-edge model.
        </p>
      </div>
      {loading && (
        <div className="px-6 py-12 text-center text-sm text-gray-500">
          Loading model…
        </div>
      )}
      {error && (
        <div className="px-6 py-4 text-sm text-amber-700">
          No trained model yet — click Train above.
        </div>
      )}
      {data && <ModelBody model={data.model} trainedAt={data.trained_at} nBacktests={data.n_backtests} />}
    </div>
  );
}


function ModelBody({
  model,
  trainedAt,
  nBacktests,
}: {
  model: TrainedModel;
  trainedAt: string;
  nBacktests: number;
}) {
  const base = model.base_profit_rate * 100;
  const topWeights = model.feature_weights
    .filter((w: SignalFeatureWeight) => Math.abs(w.weight) > 1e-4)
    .slice(0, 10);

  return (
    <>
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 border-b border-gray-100 px-6 py-4 text-sm sm:grid-cols-5">
        <Stat label="Samples" value={String(model.n_samples)} />
        <Stat label="Backtests" value={String(nBacktests)} />
        <Stat label="Base win rate" value={`${base.toFixed(1)}%`} />
        <Stat
          label="Train accuracy"
          value={
            model.train_accuracy != null
              ? `${(model.train_accuracy * 100).toFixed(1)}%`
              : "—"
          }
        />
        <Stat label="Trained" value={new Date(trainedAt).toLocaleDateString()} />
      </div>

      {!model.fitted && (
        <div className="border-b border-gray-100 bg-amber-50 px-6 py-3 text-xs text-amber-900">
          Model not fitted: {model.reason ?? "insufficient data"}. Per-signal
          rates below are empirical.
        </div>
      )}

      <div className="px-6 py-4">
        <p className="mb-2 text-xs uppercase tracking-wide text-gray-500">
          Per-signal edge
        </p>
        {model.signal_edges.length === 0 ? (
          <p className="text-sm text-gray-500">No signal-tagged trades.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Signal</th>
                  <th className="px-3 py-2 text-right font-medium">Trades</th>
                  <th className="px-3 py-2 text-right font-medium">Win %</th>
                  <th className="px-3 py-2 text-right font-medium">Pred. win %</th>
                  <th className="px-3 py-2 text-right font-medium">Lift</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {model.signal_edges.map((e: SignalEdge) => (
                  <tr key={e.name} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono text-xs">{e.name}</td>
                    <td className="px-3 py-2 text-right text-xs text-gray-600">
                      {e.num_trades}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {(e.empirical_profit_rate * 100).toFixed(1)}%
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs text-gray-600">
                      {(e.mean_predicted_prob * 100).toFixed(1)}%
                    </td>
                    <td
                      className={`px-3 py-2 text-right font-mono text-xs ${
                        e.lift_vs_base_pp > 0.05
                          ? "text-green-700"
                          : e.lift_vs_base_pp < -0.05
                            ? "text-red-700"
                            : "text-gray-600"
                      }`}
                    >
                      {e.lift_vs_base_pp > 0 ? "+" : ""}
                      {e.lift_vs_base_pp.toFixed(1)}pp
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {model.fitted && topWeights.length > 0 && (
        <div className="border-t border-gray-100 px-6 py-4">
          <p className="mb-2 text-xs uppercase tracking-wide text-gray-500">
            Top feature weights (standardized)
          </p>
          <div className="flex flex-wrap gap-2">
            {topWeights.map((w: SignalFeatureWeight) => (
              <span
                key={w.feature}
                className={`rounded px-2 py-1 font-mono text-xs ${
                  w.weight > 0
                    ? "bg-green-50 text-green-700"
                    : "bg-red-50 text-red-700"
                }`}
                title={`${w.feature}: ${w.weight.toFixed(4)}`}
              >
                {prettyFeature(w.feature)} {w.weight > 0 ? "+" : ""}
                {w.weight.toFixed(2)}
              </span>
            ))}
          </div>
        </div>
      )}
    </>
  );
}


function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className="mt-0.5 font-mono text-sm font-semibold text-navy-700">
        {value}
      </p>
    </div>
  );
}

function prettyFeature(feature: string): string {
  const m = feature.match(/^sig::(.+)::(active|value)$/);
  return m ? `${m[1]}·${m[2]}` : feature;
}
