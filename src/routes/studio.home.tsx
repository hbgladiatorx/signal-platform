import { createFileRoute, Link } from "@tanstack/react-router";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { strategies as allStrats } from "@/lib/mockData";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import type { PipelineStage } from "@/lib/types";
import { Plus } from "lucide-react";

export const Route = createFileRoute("/studio/home")({
  head: () => ({ meta: [{ title: "Studio — Bayn" }] }),
  component: StudioHome,
});

const devStrategies = [
  { ...allStrats[0], stage: "Published" as PipelineStage },
  { ...allStrats[3], stage: "Forward Testing" as PipelineStage },
  { ...allStrats[6], stage: "Out-of-Sample Passed" as PipelineStage },
  { ...allStrats[9], stage: "Backtested" as PipelineStage },
  { id: "draft-1", name: "VIX Term-Structure Carry", description: "Carry trade on VIX term structure during contango regimes.", assetClass: "options" as const, stage: "Draft" as PipelineStage, stats: { sharpe: 0, winRate: 0, sampleSize: 0, maxDrawdown: 0, liveDays: 0, subscribers: 0, avgR: 0 } },
];

const stageColors: Record<PipelineStage, string> = {
  Draft: "text-muted-foreground border-border bg-muted/30",
  Backtested: "text-cyan border-cyan/30 bg-cyan/10",
  "Out-of-Sample Passed": "text-gold border-gold/30 bg-gold/10",
  "Forward Testing": "text-options border-options/30 bg-options/10",
  Submitted: "text-stocks border-stocks/30 bg-stocks/10",
  Published: "text-futures border-futures/30 bg-futures/10",
  Rejected: "text-danger border-danger/30 bg-danger/10",
};

function StudioHome() {
  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">My strategies</h1>
          <p className="text-sm text-muted-foreground font-mono">// developer workspace</p>
        </div>
        <Button asChild className="bg-cyan text-cyan-foreground hover:bg-cyan/90">
          <Link to="/studio/new"><Plus className="mr-2 size-4" /> New strategy</Link>
        </Button>
      </div>
      <Card className="border-border bg-elevated">
        <div className="divide-y divide-border">
          {devStrategies.map((s) => (
            <div key={s.id} className="grid grid-cols-12 items-center gap-3 px-4 py-3">
              <div className="col-span-5">
                <div className="font-medium">{s.name}</div>
                <div className="text-xs text-muted-foreground">{s.description}</div>
              </div>
              <div className="col-span-2"><AssetClassBadge assetClass={s.assetClass} hideIcon /></div>
              <div className="col-span-2">
                <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-mono ${stageColors[s.stage]}`}>{s.stage}</span>
              </div>
              <div className="col-span-2 text-right font-mono text-sm text-muted-foreground">
                {s.stats.sharpe ? `Sharpe ${s.stats.sharpe.toFixed(2)}` : "—"}
              </div>
              <div className="col-span-1 text-right">
                <Button variant="ghost" size="sm">Open</Button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
