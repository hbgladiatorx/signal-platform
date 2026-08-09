import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { Brain, Cpu } from "lucide-react";
import type { BacktestMlModel } from "@/lib/types";

const pct = (n: number | null | undefined, dp = 0) =>
  n == null ? "—" : `${(n * 100).toFixed(dp)}%`;
const numf = (n: number | null | undefined, dp = 3) =>
  n == null ? "—" : n.toFixed(dp);

/** One stat chip in the model header. */
function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border bg-background/40 px-2 py-1" title={hint}>
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="font-mono text-xs text-foreground">{value}</div>
    </div>
  );
}

export function ModelCard({ model }: { model: BacktestMlModel }) {
  const fitted = model.fitted;
  return (
    <Card className="border-border bg-elevated p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          {fitted ? <Cpu className="size-4 text-violet" /> : <Brain className="size-4 text-violet" />}
          Signal-edge model
          <span
            className={cn(
              "rounded-full border px-2 py-0.5 text-[10px] font-medium",
              fitted ? "border-success/40 bg-success/10 text-success" : "border-amber-400/40 bg-amber-400/10 text-amber-400",
            )}
          >
            {fitted ? "fitted" : "not fitted"}
          </span>
        </div>
      </div>

      <p className="mt-1 text-xs text-muted-foreground">
        Logistic model predicting whether a trade is profitable from the signals active at entry.
        {!fitted && model.reason ? ` Not fitted — ${model.reason}. Empirical edges below still hold.` : ""}
      </p>

      {/* Full model stats — every number the model exposes. */}
      <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
        <Stat label="Base rate" value={pct(model.base_profit_rate)} hint="Profitable-trade rate with no model — the bar to beat." />
        <Stat label="Train acc" value={pct(model.train_accuracy, 1)} hint="In-sample accuracy of the fit." />
        <Stat label="Log loss" value={numf(model.train_log_loss)} hint="Lower is better; penalises confident wrong predictions." />
        <Stat label="Samples" value={`${model.n_samples}`} hint="Closed round-trips used to train." />
        <Stat label="Features" value={`${model.n_features}`} hint="Signal flags + numeric readings fed in." />
        <Stat label="Signals" value={`${model.signal_edges?.length ?? 0}`} hint="Distinct signals with measured edge." />
      </div>

      {/* Feature importances — which inputs move the prediction, signed + scaled. */}
      {fitted && (model.feature_weights?.length ?? 0) > 0 && (
        <FeatureWeights weights={model.feature_weights} countFeature={model.count_feature} />
      )}

      {/* Per-signal empirical vs predicted edge. */}
      <EdgeTable model={model} />
    </Card>
  );
}

function FeatureWeights({
  weights,
  countFeature,
}: {
  weights: { feature: string; weight: number }[];
  countFeature?: string;
}) {
  const sorted = [...weights].sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
  const maxAbs = Math.max(1e-9, ...sorted.map((w) => Math.abs(w.weight)));
  return (
    <div className="mt-3">
      <div className="mb-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
        Feature importance (standardized weights)
      </div>
      <div className="space-y-1">
        {sorted.map((w) => {
          const frac = Math.abs(w.weight) / maxAbs;
          const pos = w.weight >= 0;
          return (
            <div key={w.feature} className="flex items-center gap-2 text-xs">
              <span className="w-40 shrink-0 truncate font-mono text-[11px]" title={w.feature}>
                {w.feature}
                {w.feature === countFeature ? " ·#" : ""}
              </span>
              <div className="relative h-3 flex-1 overflow-hidden rounded bg-background/50">
                <div
                  className={cn("absolute top-0 h-full", pos ? "left-1/2 bg-cyan/60" : "right-1/2 bg-danger/60")}
                  style={{ width: `${(frac * 50).toFixed(1)}%` }}
                />
                <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
              </div>
              <span className={cn("w-14 shrink-0 text-right font-mono text-[11px]", pos ? "text-cyan" : "text-danger")}>
                {pos ? "+" : ""}{w.weight.toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>
      <p className="mt-1 text-[10px] text-muted-foreground">
        Positive (cyan) pushes toward a profitable trade; negative (red) toward a loss. Magnitudes are standardized, so they compare directly.
      </p>
    </div>
  );
}

function EdgeTable({ model }: { model: BacktestMlModel }) {
  const edges = [...(model.signal_edges ?? [])].sort((a, b) => (b.lift_vs_base_pp ?? 0) - (a.lift_vs_base_pp ?? 0));
  if (edges.length === 0) {
    return <p className="mt-3 text-sm text-muted-foreground">No per-signal edges (strategy emits no signals).</p>;
  }
  return (
    <div className="mt-3">
      <div className="mb-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">Per-signal edge</div>
      <div className="overflow-hidden rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/20 text-[10px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="p-2 text-left">Signal</th>
              <th className="p-2 text-right">Trades</th>
              <th className="p-2 text-right" title="Actual profitable-trade rate when this signal was active">Empirical</th>
              <th className="p-2 text-right" title="Model's mean predicted profit probability for those trades">Predicted</th>
              <th className="p-2 text-right" title="Empirical rate minus the base rate, in percentage points">Edge vs base</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {edges.map((e) => {
              const lift = e.lift_vs_base_pp;
              return (
                <tr key={e.name}>
                  <td className="p-2 font-medium">{e.name}</td>
                  <td className="p-2 text-right font-mono text-xs">{e.num_trades}</td>
                  <td className="p-2 text-right font-mono text-xs">{pct(e.empirical_profit_rate)}</td>
                  <td className="p-2 text-right font-mono text-xs">{pct(e.mean_predicted_prob)}</td>
                  <td className={cn("p-2 text-right font-mono text-xs", lift > 1 ? "text-cyan" : lift < -1 ? "text-danger" : "text-muted-foreground")}>
                    {lift >= 0 ? "+" : ""}{lift.toFixed(0)}pp
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
