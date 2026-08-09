import { createFileRoute, Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { getDevStrategy, getBacktestsForStrategy, getPersonalSignals } from "@/lib/api/studio";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { StageBadge } from "@/components/common/StageBadge";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { PipelineProgress } from "@/components/common/PipelineProgress";
import { StrategyGraphPreview } from "@/components/studio/StrategyGraphPreview";
import { DirectionPill } from "@/components/common/DirectionPill";
import { StatusPill } from "@/components/common/StatusPill";
import { Edit3, ArrowLeft } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

export const Route = createFileRoute("/studio/strategy/$id")({
  head: () => ({ meta: [{ title: "Strategy — Bayn Studio" }] }),
  component: DevStrategyDetail,
});

function DevStrategyDetail() {
  const { id } = useParams({ from: "/studio/strategy/$id" });
  const { data: strategy } = useQuery({ queryKey: ["devStrategy", id], queryFn: () => getDevStrategy(id) });
  const { data: backtests } = useQuery({ queryKey: ["bts", id], queryFn: () => getBacktestsForStrategy(id) });
  const { data: sigs } = useQuery({ queryKey: ["personalSignals", id], queryFn: () => getPersonalSignals({ strategyId: id }) });

  if (!strategy) return <div className="p-6 text-muted-foreground">Loading…</div>;

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-start gap-3">
        <Button asChild variant="ghost" size="sm"><Link to="/studio/strategies"><ArrowLeft className="mr-1 size-4" /> Strategies</Link></Button>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">{strategy.name}</h1>
            <AssetClassBadge assetClass={strategy.assetClass} />
            <StageBadge stage={strategy.stage} />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{strategy.description}</p>
        </div>
        <Button asChild className="bg-violet text-violet-foreground hover:bg-violet/90">
          <Link to="/studio/builder/$id" params={{ id: strategy.id }}><Edit3 className="mr-2 size-4" /> Edit in Builder</Link>
        </Button>
      </div>

      <Card className="border-border bg-elevated p-4">
        <div className="mb-3 text-xs uppercase tracking-wider text-muted-foreground">Pipeline stage</div>
        <PipelineProgress current={strategy.stage} />
      </Card>

      <Tabs defaultValue="graph">
        <TabsList>
          <TabsTrigger value="graph">Graph</TabsTrigger>
          <TabsTrigger value="backtests">Backtests</TabsTrigger>
          <TabsTrigger value="live">Live Performance</TabsTrigger>
          <TabsTrigger value="signals">Signals</TabsTrigger>
          <TabsTrigger value="versions">Versions</TabsTrigger>
          {strategy.submissionStatus && <TabsTrigger value="submission">Bayn Submission</TabsTrigger>}
        </TabsList>

        <TabsContent value="graph" className="mt-4">
          <Card className="border-border bg-elevated p-4">
            <div className="h-[460px]"><StrategyGraphPreview graph={strategy.graph} className="h-full" /></div>
          </Card>
        </TabsContent>

        <TabsContent value="backtests" className="mt-4">
          <Card className="border-border bg-elevated">
            <div className="divide-y divide-border">
              {(backtests ?? []).map((b) => (
                <Link key={b.id} to="/studio/backtests/$strategyId" params={{ strategyId: id }} className="grid grid-cols-12 items-center gap-3 px-4 py-3 hover:bg-muted/30">
                  <div className="col-span-3 font-mono text-xs">{new Date(b.ranAt).toLocaleString()}</div>
                  <div className="col-span-2 text-xs text-muted-foreground">{b.params.startDate} → {b.params.endDate}</div>
                  <div className="col-span-2 text-right font-mono">{(b.stats.totalReturn * 100).toFixed(1)}%</div>
                  <div className="col-span-2 text-right font-mono">Sharpe {b.stats.sharpe.toFixed(2)}</div>
                  <div className="col-span-2 text-right font-mono">{b.stats.totalTrades} trades</div>
                  <div className="col-span-1 text-right text-xs text-muted-foreground">→</div>
                </Link>
              ))}
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="live" className="mt-4">
          <Card className="border-border bg-elevated p-6 text-sm text-muted-foreground">
            {strategy.liveSinceDays ? (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
                <Stat label="Live days" value={String(strategy.liveSinceDays)} />
                <Stat label="Signals fired" value={String(sigs?.length ?? 0)} />
                <Stat label="Win rate" value={strategy.stats ? `${(strategy.stats.winRate * 100).toFixed(0)}%` : "—"} />
                <Stat label="Avg R" value={strategy.stats ? `${strategy.stats.avgR.toFixed(2)}R` : "—"} />
              </div>
            ) : "Not deployed live yet."}
          </Card>
        </TabsContent>

        <TabsContent value="signals" className="mt-4">
          <Card className="border-border bg-elevated">
            <div className="divide-y divide-border">
              {(sigs ?? []).map((sig) => (
                <div key={sig.id} className="grid grid-cols-12 items-center gap-3 px-4 py-3">
                  <div className="col-span-3 font-mono text-xs">{formatDistanceToNow(new Date(sig.firedAt), { addSuffix: true })}</div>
                  <div className="col-span-2 font-mono text-xs text-violet">{sig.symbol}</div>
                  <div className="col-span-1"><DirectionPill direction={sig.direction} /></div>
                  <div className="col-span-4 font-mono text-xs text-muted-foreground"><span className="text-foreground">{sig.entry}</span> · stop {sig.stop} · tgt {sig.target}</div>
                  <div className="col-span-2 flex justify-end"><StatusPill status={sig.status} /></div>
                </div>
              ))}
              {!sigs?.length && <div className="p-8 text-center text-sm text-muted-foreground">No signals yet.</div>}
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="versions" className="mt-4">
          <Card className="border-border bg-elevated">
            <div className="divide-y divide-border">
              {strategy.versions.map((v) => (
                <div key={v.id} className="flex items-center justify-between px-4 py-3 text-sm">
                  <div>
                    <span className="font-mono text-violet">{v.id}</span> · {v.note}
                  </div>
                  <span className="text-xs text-muted-foreground">{formatDistanceToNow(new Date(v.createdAt), { addSuffix: true })}</span>
                </div>
              ))}
            </div>
          </Card>
        </TabsContent>

        {strategy.submissionStatus && (
          <TabsContent value="submission" className="mt-4">
            <Card className="border-border bg-elevated p-6 space-y-3">
              <div className="flex items-center gap-2"><span className="text-xs uppercase tracking-wider text-muted-foreground">Status</span> <StageBadge stage={strategy.submissionStatus as any} /></div>
              {strategy.submissionNotes && <p className="text-sm text-muted-foreground">{strategy.submissionNotes}</p>}
            </Card>
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-background/40 p-3">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-xl">{value}</div>
    </div>
  );
}
