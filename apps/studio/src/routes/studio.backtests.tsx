import { createFileRoute, Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getDevStrategies, getBacktestsForStrategy } from "@/lib/api/studio";
import { Card } from "@/components/ui/card";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { formatDistanceToNow } from "date-fns";
import { Button } from "@/components/ui/button";
import { QueryState } from "@/components/common/QueryState";
import { LayoutGrid, List as ListIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/studio/backtests")({
  head: () => ({ meta: [{ title: "Backtests — Bayn Studio" }] }),
  component: BacktestsList,
});

type View = "grid" | "list";
const VIEW_KEY = "studio.backtests.view";

function BacktestsList() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const stratQuery = useQuery({ queryKey: ["devStrategies"], queryFn: getDevStrategies });
  const [view, setView] = useState<View>(() => {
    if (typeof window === "undefined") return "grid";
    return (window.localStorage.getItem(VIEW_KEY) as View) || "grid";
  });
  const pickView = (v: View) => {
    setView(v);
    try { window.localStorage.setItem(VIEW_KEY, v); } catch { /* ignore */ }
  };

  if (pathname !== "/studio/backtests") return <Outlet />;

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Backtests</h1>
          <p className="text-sm text-muted-foreground">Open a strategy to view its full backtest history.</p>
        </div>
        {/* Grid / list toggle — choice persists locally. */}
        <div className="flex items-center gap-0.5 rounded-md border border-border bg-elevated p-0.5">
          <Button variant="ghost" size="icon" aria-label="Grid view"
            className={cn("size-8", view === "grid" && "bg-violet/15 text-violet")}
            onClick={() => pickView("grid")}>
            <LayoutGrid className="size-4" />
          </Button>
          <Button variant="ghost" size="icon" aria-label="List view"
            className={cn("size-8", view === "list" && "bg-violet/15 text-violet")}
            onClick={() => pickView("list")}>
            <ListIcon className="size-4" />
          </Button>
        </div>
      </div>

      <QueryState
        query={stratQuery}
        skeletonRows={6}
        emptyHeadline="No strategies yet"
        emptyBody="Build a strategy in the Copilot to run your first backtest."
        emptyCta={<Button asChild size="sm"><Link to="/studio/copilot">Open Copilot</Link></Button>}
      >
        {(strategies) =>
          view === "grid" ? (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
              {strategies.map((s) => (
                <StrategyBacktestCard key={s.id} strategyId={s.id} name={s.name} description={s.description} assetClass={s.assetClass} />
              ))}
            </div>
          ) : (
            <Card className="overflow-hidden border-border bg-elevated">
              <div className="grid grid-cols-12 gap-2 border-b border-border px-4 py-2 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                <div className="col-span-5">Strategy</div>
                <div className="col-span-2 text-right">Return</div>
                <div className="col-span-1 text-right">Sharpe</div>
                <div className="col-span-1 text-right">Max DD</div>
                <div className="col-span-3 text-right">Runs · last</div>
              </div>
              <div className="divide-y divide-border">
                {strategies.map((s) => (
                  <StrategyBacktestRow key={s.id} strategyId={s.id} name={s.name} assetClass={s.assetClass} />
                ))}
              </div>
            </Card>
          )
        }
      </QueryState>
    </div>
  );
}

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const returnClass = (v?: number) => (v == null ? "text-muted-foreground" : v >= 0 ? "text-emerald-500" : "text-red-500");

function StrategyBacktestCard({ strategyId, name, description, assetClass }: { strategyId: string; name: string; description: string; assetClass: any }) {
  const { data } = useQuery({ queryKey: ["bts", strategyId], queryFn: () => getBacktestsForStrategy(strategyId) });
  const latest = data?.[0];
  return (
    <Link
      to="/studio/backtests/$strategyId"
      params={{ strategyId }}
      search={latest ? { runId: latest.id } : {}}
      preload="intent"
      className="block"
    >
      <Card className="h-full border-border bg-elevated p-4 transition-colors hover:border-violet/30 cursor-pointer">
        <div className="mb-1 flex items-start justify-between gap-2">
          <h3 className="font-semibold">{name}</h3>
          <AssetClassBadge assetClass={assetClass} hideIcon />
        </div>
        <p className="mb-3 text-xs text-muted-foreground line-clamp-2">{description}</p>
        {latest ? (
          <div className="grid grid-cols-3 gap-2 border-t border-border pt-3 text-center">
            <div><div className={cn("font-mono text-sm", returnClass(latest.stats.totalReturn))}>{pct(latest.stats.totalReturn)}</div><div className="text-[10px] uppercase text-muted-foreground">Return</div></div>
            <div><div className="font-mono text-sm">{latest.stats.sharpe.toFixed(2)}</div><div className="text-[10px] uppercase text-muted-foreground">Sharpe</div></div>
            <div><div className="font-mono text-sm">{(latest.stats.maxDrawdown * 100).toFixed(0)}%</div><div className="text-[10px] uppercase text-muted-foreground">Max DD</div></div>
          </div>
        ) : <div className="text-xs text-muted-foreground">No runs yet.</div>}
        <div className="mt-3 text-[11px] text-muted-foreground">
          {data?.length ?? 0} run{(data?.length ?? 0) === 1 ? "" : "s"} · last {latest ? formatDistanceToNow(new Date(latest.ranAt), { addSuffix: true }) : "—"}
        </div>
      </Card>
    </Link>
  );
}

function StrategyBacktestRow({ strategyId, name, assetClass }: { strategyId: string; name: string; assetClass: any }) {
  const { data } = useQuery({ queryKey: ["bts", strategyId], queryFn: () => getBacktestsForStrategy(strategyId) });
  const latest = data?.[0];
  const runs = data?.length ?? 0;
  return (
    <Link
      to="/studio/backtests/$strategyId"
      params={{ strategyId }}
      search={latest ? { runId: latest.id } : {}}
      preload="intent"
      className="grid grid-cols-12 items-center gap-2 px-4 py-3 text-sm transition-colors hover:bg-muted/30"
    >
      <div className="col-span-5 flex items-center gap-2 min-w-0">
        <AssetClassBadge assetClass={assetClass} hideIcon />
        <span className="truncate font-medium">{name}</span>
      </div>
      <div className={cn("col-span-2 text-right font-mono", returnClass(latest?.stats.totalReturn))}>
        {latest ? pct(latest.stats.totalReturn) : "—"}
      </div>
      <div className="col-span-1 text-right font-mono">{latest ? latest.stats.sharpe.toFixed(2) : "—"}</div>
      <div className="col-span-1 text-right font-mono text-muted-foreground">{latest ? `${(latest.stats.maxDrawdown * 100).toFixed(0)}%` : "—"}</div>
      <div className="col-span-3 text-right text-xs text-muted-foreground">
        {runs} run{runs === 1 ? "" : "s"} · {latest ? formatDistanceToNow(new Date(latest.ranAt), { addSuffix: true }) : "—"}
      </div>
    </Link>
  );
}
