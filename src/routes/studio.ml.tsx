import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Brain, Cpu, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { getMlStrategies, getMlModel, trainMlModel, type MlStrategyStats } from "@/lib/api/ml";

export const Route = createFileRoute("/studio/ml")({
  head: () => ({ meta: [{ title: "ML models — Bayn Studio" }] }),
  component: MlPage,
});

const pct = (n: number | null | undefined, dp = 0) =>
  n == null ? "—" : `${(n * 100).toFixed(dp)}%`;

function MlPage() {
  const { data, isLoading } = useQuery({ queryKey: ["mlStrategies"], queryFn: getMlStrategies });
  const [selected, setSelected] = useState<string | null>(null);

  const list = data ?? [];
  const active = selected ?? list.find((s) => s.has_model)?.strategy_name ?? list[0]?.strategy_name ?? null;

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Brain className="size-6 text-violet" /> ML models
        </h1>
        <p className="text-sm text-muted-foreground">
          Cross-backtest signal-edge models. Every backtest you run contributes per-trade
          samples; train a model per strategy over the accumulated store to learn which
          signals actually predict profitable trades.
        </p>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : list.length === 0 ? (
        <Card className="border-dashed border-border bg-elevated p-8 text-center text-sm text-muted-foreground">
          No training samples yet. Run a few backtests on signal-emitting strategies to
          accumulate the feature store, then come back to train a model.
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-5">
          {/* Strategy table */}
          <Card className="border-border bg-elevated lg:col-span-3">
            <div className="border-b border-border p-3 text-sm font-medium">Strategies</div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/20 text-[10px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="p-2 text-left">Strategy</th>
                    <th className="p-2 text-right">Samples</th>
                    <th className="p-2 text-right">Backtests</th>
                    <th className="p-2 text-right">Base win</th>
                    <th className="p-2 text-right">Model</th>
                    <th className="p-2"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {list.map((s) => (
                    <StrategyRow
                      key={s.strategy_name}
                      s={s}
                      active={s.strategy_name === active}
                      onSelect={() => setSelected(s.strategy_name)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Model panel */}
          <div className="lg:col-span-2">
            {active ? <ModelPanel key={active} name={active} /> : null}
          </div>
        </div>
      )}
    </div>
  );
}

function StrategyRow({ s, active, onSelect }: { s: MlStrategyStats; active: boolean; onSelect: () => void }) {
  const qc = useQueryClient();
  const train = useMutation({
    mutationFn: () => trainMlModel(s.strategy_name),
    onSuccess: (r) => {
      toast.success(`Trained on ${r.n_samples} samples`);
      qc.invalidateQueries({ queryKey: ["mlStrategies"] });
      qc.invalidateQueries({ queryKey: ["mlModel", s.strategy_name] });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Training failed"),
  });
  return (
    <tr className={cn("cursor-pointer hover:bg-muted/10", active && "bg-violet/5")} onClick={onSelect}>
      <td className="p-2 font-medium">{s.strategy_name}</td>
      <td className="p-2 text-right font-mono text-xs">{s.n_samples}</td>
      <td className="p-2 text-right font-mono text-xs">{s.n_backtests}</td>
      <td className="p-2 text-right font-mono text-xs">{pct(s.base_profit_rate)}</td>
      <td className="p-2 text-right">
        {s.has_model
          ? <span className="rounded-full border border-success/30 bg-success/10 px-2 py-0.5 text-[10px] text-success">trained</span>
          : <span className="text-[10px] text-muted-foreground">none</span>}
      </td>
      <td className="p-2 text-right">
        <Button
          size="sm" variant="outline" className="h-7 gap-1 text-xs"
          disabled={train.isPending || s.n_samples < 8}
          onClick={(e) => { e.stopPropagation(); train.mutate(); }}
          title={s.n_samples < 8 ? "Need at least 8 samples to train" : ""}
        >
          {train.isPending ? <Loader2 className="size-3 animate-spin" /> : <RefreshCw className="size-3" />}
          {s.has_model ? "Retrain" : "Train"}
        </Button>
      </td>
    </tr>
  );
}

function ModelPanel({ name }: { name: string }) {
  const { data: model, isLoading } = useQuery({
    queryKey: ["mlModel", name],
    queryFn: () => getMlModel(name),
  });

  if (isLoading) return <Card className="border-border bg-elevated p-4 text-sm text-muted-foreground">Loading model…</Card>;
  if (!model) {
    return (
      <Card className="border-dashed border-border bg-elevated p-6 text-center text-sm text-muted-foreground">
        No trained model for <span className="font-medium text-foreground">{name}</span> yet. Hit Train.
      </Card>
    );
  }

  const edges = [...(model.model.signal_edges ?? [])].sort(
    (a, b) => (b.lift_vs_base_pp ?? 0) - (a.lift_vs_base_pp ?? 0),
  );

  return (
    <Card className="border-violet/30 bg-elevated p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Cpu className="size-4 text-violet" /> {model.strategy_name}
      </div>
      <div className="mt-1 flex flex-wrap gap-3 font-mono text-[11px] text-muted-foreground">
        <span>{model.n_samples} samples</span>
        <span>{model.n_backtests} backtests</span>
        <span>trained {new Date(model.trained_at).toLocaleDateString()}</span>
      </div>

      <div className="mt-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Signal edge (vs base rate)</div>
      {edges.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">No per-signal edges in this model.</p>
      ) : (
        <div className="mt-2 space-y-1.5">
          {edges.map((e) => {
            const lift = e.lift_vs_base_pp ?? 0;
            const pos = lift >= 0;
            return (
              <div key={e.name} className="flex items-center gap-2">
                <div className="w-28 shrink-0 truncate text-sm" title={e.name}>{e.name}</div>
                <div className="relative h-4 flex-1 rounded bg-muted/20">
                  <div
                    className={cn("absolute top-0 h-4 rounded", pos ? "left-1/2 bg-cyan" : "right-1/2 bg-danger")}
                    style={{ width: `${Math.min(50, Math.abs(lift) * 1.5)}%` }}
                  />
                  <div className="absolute left-1/2 top-0 h-4 w-px bg-border" />
                </div>
                <div className={cn("w-12 shrink-0 text-right font-mono text-xs", pos ? "text-cyan" : "text-danger")}>
                  {pos ? "+" : ""}{lift.toFixed(0)}pp
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
