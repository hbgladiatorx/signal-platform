import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { zodValidator, fallback } from "@tanstack/zod-adapter";
import { z } from "zod";
import { toast } from "sonner";
import { deleteUserStrategy, getDevStrategies, isBuiltinStrategy, runBacktest } from "@/lib/api/studio";
import { BacktestRunModal } from "@/components/studio/BacktestRunModal";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StageBadge } from "@/components/common/StageBadge";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { formatDistanceToNow } from "date-fns";
import { Play, Plus, Trash2 } from "lucide-react";
import type { AssetClass, DevStrategy, PipelineStage } from "@/lib/types";

// `?stage=` pre-filters the list (the dashboard status cards link here). An
// unknown or absent value falls back to "all stages".
const STAGES: PipelineStage[] = [
  "Draft", "Backtested", "Out-of-Sample Passed", "Forward Testing", "Live",
  "Submitted", "Under Review", "Published", "Rejected",
];

const searchSchema = z.object({
  stage: fallback(z.enum(STAGES as [PipelineStage, ...PipelineStage[]]).optional(), undefined),
});

export const Route = createFileRoute("/studio/strategies")({
  head: () => ({ meta: [{ title: "My Strategies — Bayn Studio" }] }),
  validateSearch: zodValidator(searchSchema),
  component: StrategiesList,
});

function StrategiesList() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { stage } = Route.useSearch();
  const { data } = useQuery({ queryKey: ["devStrategies"], queryFn: getDevStrategies });
  const [ac, setAc] = useState<"all" | AssetClass>("all");
  const st: "all" | PipelineStage = stage ?? "all";
  // The stage filter lives in the URL so a linked-in filter and the dropdown
  // stay the same piece of state.
  const setSt = (v: "all" | PipelineStage) =>
    navigate({ to: "/studio/strategies", search: v === "all" ? {} : { stage: v } });
  const [q, setQ] = useState("");
  // Two-step inline confirm: the first Delete click arms this row.
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  // Strategy queued for a direct (LLM-free) backtest run via the modal.
  const [runFor, setRunFor] = useState<DevStrategy | null>(null);

  async function onDelete(s: DevStrategy) {
    setDeletingId(s.id);
    try {
      await deleteUserStrategy(s.id);
      await qc.invalidateQueries({ queryKey: ["devStrategies"] });
      toast.success(`Deleted "${s.name}"`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't delete that strategy");
    } finally {
      setDeletingId(null);
      setConfirmId(null);
    }
  }

  const list = useMemo(() => {
    let arr = data ?? [];
    if (ac !== "all") arr = arr.filter((s) => s.assetClass === ac);
    if (st !== "all") arr = arr.filter((s) => s.stage === st);
    if (q) arr = arr.filter((s) => (s.name + s.description).toLowerCase().includes(q.toLowerCase()));
    return arr;
  }, [data, ac, st, q]);

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">My strategies</h1>
          <p className="text-sm text-muted-foreground">All strategies you've built in Studio.</p>
        </div>
        <Button asChild className="bg-violet text-violet-foreground hover:bg-violet/90">
          <Link to="/studio/builder/$id" params={{ id: "new" }}><Plus className="mr-2 size-4" /> New strategy</Link>
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" className="h-9 max-w-xs bg-elevated" />
        <Select value={ac} onValueChange={(v: any) => setAc(v)}>
          <SelectTrigger className="h-9 w-40 bg-elevated"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All asset classes</SelectItem>
            <SelectItem value="stocks">Stocks</SelectItem>
            <SelectItem value="crypto">Crypto</SelectItem>
            <SelectItem value="options">Options</SelectItem>
            <SelectItem value="futures">Futures</SelectItem>
          </SelectContent>
        </Select>
        <Select value={st} onValueChange={(v: any) => setSt(v)}>
          <SelectTrigger className="h-9 w-44 bg-elevated"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All stages</SelectItem>
            {STAGES.map((s) => (
              <SelectItem key={s} value={s}>{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card className="border-border bg-elevated">
        <div className="grid grid-cols-12 gap-2 border-b border-border px-4 py-2 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
          <div className="col-span-2">Name</div>
          <div className="col-span-1">Asset</div>
          <div className="col-span-1">Status</div>
          <div className="col-span-1 text-right">Return</div>
          <div className="col-span-1 text-right">PF</div>
          <div className="col-span-1 text-right">Sharpe</div>
          <div className="col-span-1 text-right">Win</div>
          <div className="col-span-1 text-right">Max DD</div>
          <div className="col-span-1 text-right">Trades</div>
          <div className="col-span-2 text-right">Actions</div>
        </div>
        <div className="divide-y divide-border">
          {list.map((s) => {
            const st = s.stats;
            const ret = st?.totalReturn;
            return (
            <div key={s.id} className="grid grid-cols-12 items-center gap-2 px-4 py-3 text-sm">
              <div className="col-span-2">
                <Link to="/studio/strategy/$id" params={{ id: s.id }} className="font-medium hover:text-violet">{s.name}</Link>
                <div className="text-xs text-muted-foreground line-clamp-1">
                  {s.lastRunAt ? `Last run ${formatDistanceToNow(new Date(s.lastRunAt), { addSuffix: true })}` : (s.description || "Not yet backtested")}
                </div>
              </div>
              <div className="col-span-1"><AssetClassBadge assetClass={s.assetClass} hideIcon /></div>
              <div className="col-span-1"><StageBadge stage={s.stage} /></div>
              <div className={`col-span-1 text-right font-mono ${ret == null ? "" : ret >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                {ret == null ? "—" : `${ret >= 0 ? "+" : ""}${(ret * 100).toFixed(1)}%`}
              </div>
              <div className="col-span-1 text-right font-mono">{st?.profitFactor != null ? st.profitFactor.toFixed(2) : "—"}</div>
              <div className="col-span-1 text-right font-mono">{st?.sharpe != null ? st.sharpe.toFixed(2) : "—"}</div>
              <div className="col-span-1 text-right font-mono">{st ? `${(st.winRate * 100).toFixed(0)}%` : "—"}</div>
              <div className="col-span-1 text-right font-mono text-muted-foreground">{st ? `${(st.maxDrawdown * 100).toFixed(0)}%` : "—"}</div>
              <div className="col-span-1 text-right font-mono text-muted-foreground">{st?.totalTrades ?? "—"}</div>
              <div className="col-span-2 flex justify-end gap-1">
                <Button size="sm" variant="ghost" title="Backtest now (no AI)" onClick={() => setRunFor(s)}>
                  <Play className="size-3.5" />
                </Button>
                <Button size="sm" variant="ghost" asChild>
                  <Link to="/studio/builder/$id" params={{ id: s.id }}>Edit</Link>
                </Button>
                {/* Built-ins live in the platform's library, not the user's —
                    there's no row to delete. */}
                {!isBuiltinStrategy(s.id) && (
                  confirmId === s.id ? (
                    <>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-danger hover:text-danger"
                        disabled={deletingId === s.id}
                        onClick={() => onDelete(s)}
                      >
                        {deletingId === s.id ? "Deleting…" : "Confirm"}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmId(null)}>Cancel</Button>
                    </>
                  ) : (
                    <Button size="sm" variant="ghost" title="Delete strategy" onClick={() => setConfirmId(s.id)}>
                      <Trash2 className="size-3.5" />
                    </Button>
                  )
                )}
              </div>
            </div>
            );
          })}
          {list.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">No strategies match your filters.</div>
          )}
        </div>
      </Card>

      {/* Direct backtest — runs the strategy's existing source (built-ins and
          already-built strategies) without the LLM translate step. */}
      {runFor && (
        <BacktestRunModal
          open={!!runFor}
          onOpenChange={(o) => { if (!o) setRunFor(null); }}
          assetClass={runFor.assetClass}
          allowAssetSwitch
          onRun={async (p) => {
            const run = await runBacktest(runFor.id, p);
            setRunFor(null);
            navigate({
              to: "/studio/backtests/$strategyId",
              params: { strategyId: run.strategyId },
              search: { runId: run.id } as never,
            });
          }}
        />
      )}
    </div>
  );
}
