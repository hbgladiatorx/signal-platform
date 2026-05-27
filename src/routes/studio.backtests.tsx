import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { getDevStrategies, getBacktestsForStrategy } from "@/lib/api/studio";
import { Card } from "@/components/ui/card";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { formatDistanceToNow } from "date-fns";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/studio/backtests")({
  head: () => ({ meta: [{ title: "Backtests — Bayn Studio" }] }),
  component: BacktestsList,
});

function BacktestsList() {
  const { data: strategies } = useQuery({ queryKey: ["devStrategies"], queryFn: getDevStrategies });
  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Backtests</h1>
        <p className="text-sm text-muted-foreground">Open a strategy to view its full backtest history.</p>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {(strategies ?? []).map((s) => (
          <StrategyBacktestCard key={s.id} strategyId={s.id} name={s.name} description={s.description} assetClass={s.assetClass} />
        ))}
      </div>
    </div>
  );
}

function StrategyBacktestCard({ strategyId, name, description, assetClass }: { strategyId: string; name: string; description: string; assetClass: any }) {
  const { data } = useQuery({ queryKey: ["bts", strategyId], queryFn: () => getBacktestsForStrategy(strategyId) });
  const latest = data?.[0];
  return (
    <Link to="/studio/backtests/$strategyId" params={{ strategyId }}>
      <Card className="h-full border-border bg-elevated p-4 transition-colors hover:border-violet/30">
        <div className="mb-1 flex items-start justify-between gap-2">
          <h3 className="font-semibold">{name}</h3>
          <AssetClassBadge assetClass={assetClass} hideIcon />
        </div>
        <p className="mb-3 text-xs text-muted-foreground line-clamp-2">{description}</p>
        {latest ? (
          <div className="grid grid-cols-3 gap-2 border-t border-border pt-3 text-center">
            <div><div className="font-mono text-sm">{(latest.stats.totalReturn * 100).toFixed(1)}%</div><div className="text-[10px] uppercase text-muted-foreground">Return</div></div>
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
