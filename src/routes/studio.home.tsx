import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { getDevStrategies, getPersonalSignals, getBacktestsForStrategy } from "@/lib/api/studio";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StageBadge } from "@/components/common/StageBadge";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { DirectionPill } from "@/components/common/DirectionPill";
import { StatusPill } from "@/components/common/StatusPill";
import { formatDistanceToNow } from "date-fns";
import { Plus, Layers, FlaskConical, Activity, Inbox } from "lucide-react";
import type { PipelineStage } from "@/lib/types";
import { CustomizeButton } from "@/components/common/CustomizeButton";

export const Route = createFileRoute("/studio/home")({
  head: () => ({ meta: [{ title: "Studio — Bayn" }] }),
  component: StudioHome,
});

const STAGE_GROUPS: Array<{ label: string; stages: PipelineStage[]; accent: string }> = [
  { label: "Draft", stages: ["Draft"], accent: "text-muted-foreground" },
  { label: "Backtesting", stages: ["Backtested", "Out-of-Sample Passed"], accent: "text-cyan" },
  { label: "Forward Testing", stages: ["Forward Testing"], accent: "text-options" },
  { label: "Live", stages: ["Live"], accent: "text-futures" },
  { label: "Submitted", stages: ["Submitted", "Under Review"], accent: "text-violet" },
];

function StudioHome() {
  const strategies = useQuery({ queryKey: ["devStrategies"], queryFn: getDevStrategies });
  const sigs = useQuery({ queryKey: ["personalSignals", 6], queryFn: () => getPersonalSignals({ limit: 6 }) });

  const list = strategies.data ?? [];

  return (
    <div className="space-y-6 p-4 md:p-6">
      {/* Hero header — gradient violet panel */}
      <div
        className="relative overflow-hidden rounded-xl border border-violet/30 p-5"
        style={{
          background:
            "linear-gradient(135deg, color-mix(in oklab, var(--violet) 14%, var(--background)) 0%, var(--background) 65%)",
        }}
      >
        <div className="pointer-events-none absolute -right-16 -top-16 size-48 rounded-full bg-violet/20 blur-3xl" />
        <div className="relative flex flex-wrap items-end justify-between gap-3">
          <div className="space-y-1.5">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-violet/40 bg-violet/10 px-2 py-0.5 text-[10px] font-mono uppercase tracking-[0.18em] text-violet">
              Private workspace
            </span>
            <h1 className="text-2xl font-semibold tracking-tight">My Studio</h1>
            <p className="font-mono text-xs text-muted-foreground">
              // strategies, backtests, and personal signals — only visible to you
            </p>
          </div>
          <div className="flex items-center gap-2">
            <CustomizeButton mode="studio" />
            <Button asChild className="bg-violet text-violet-foreground hover:bg-violet/90">
              <Link to="/studio/builder/$id" params={{ id: "new" }}>
                <Plus className="mr-2 size-4" /> New strategy
              </Link>
            </Button>
          </div>
        </div>
      </div>

      {/* Summary tiles */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {STAGE_GROUPS.map((g) => {
          const count = list.filter((s) => g.stages.includes(s.stage)).length;
          return (
            <Card key={g.label} className="border-border bg-elevated p-4 transition-colors hover:border-violet/30">
              <div className={`text-[10px] uppercase tracking-[0.18em] ${g.accent}`}>{g.label}</div>
              <div className="mt-1 font-mono text-3xl tabular-nums">{count}</div>
            </Card>
          );
        })}
      </div>

      {/* Recent personal signals */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Recent personal signals</h2>
          <Button variant="ghost" size="sm" asChild><Link to="/studio/signals">View all →</Link></Button>
        </div>
        <Card className="border-border bg-elevated">
          {!sigs.data?.length ? (
            <div className="p-6 text-center text-sm text-muted-foreground">
              <Inbox className="mx-auto mb-2 size-8 opacity-50" />
              No live signals yet. Deploy a strategy to start receiving signals from your own rules.
            </div>
          ) : (
            <div className="divide-y divide-border">
              {sigs.data.map((sig) => (
                <div key={sig.id} className="grid grid-cols-12 items-center gap-3 px-4 py-3">
                  <div className="col-span-2 text-xs text-muted-foreground">{formatDistanceToNow(new Date(sig.firedAt), { addSuffix: true })}</div>
                  <div className="col-span-4 truncate">
                    <div className="truncate text-sm font-medium">{sig.ownStrategyName}</div>
                    <div className="font-mono text-xs text-violet">{sig.symbol}</div>
                  </div>
                  <div className="col-span-1"><DirectionPill direction={sig.direction} /></div>
                  <div className="col-span-3 font-mono text-xs text-muted-foreground">
                    <span className="text-foreground">{sig.entry}</span> · stop {sig.stop} · tgt {sig.target}
                  </div>
                  <div className="col-span-2 flex justify-end"><StatusPill status={sig.status} /></div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </section>

      {/* Active backtests + Recent activity */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="border-border bg-elevated p-5">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium"><FlaskConical className="size-4 text-violet" /> Active backtests</div>
          <div className="space-y-2 text-sm text-muted-foreground">
            {list.slice(0, 2).map((s) => (
              <div key={s.id} className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-foreground">{s.name}</span>
                  <span className="font-mono text-xs">{Math.floor(60 + Math.random() * 30)}%</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div className="h-full bg-violet" style={{ width: `${60 + Math.random() * 30}%` }} />
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card className="border-border bg-elevated p-5">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium"><Activity className="size-4 text-violet" /> Recent activity</div>
          <ul className="space-y-2 text-sm">
            {list.flatMap((s) => s.versions.slice(0, 1).map((v) => ({ s, v }))).slice(0, 5).map(({ s, v }) => (
              <li key={s.id + v.id} className="flex items-center justify-between text-muted-foreground">
                <span><span className="text-foreground">{s.name}</span> · {v.note}</span>
                <span className="font-mono text-xs">{formatDistanceToNow(new Date(v.createdAt), { addSuffix: true })}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {/* My strategies summary */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-2"><Layers className="size-4" /> My strategies</h2>
          <Button variant="ghost" size="sm" asChild><Link to="/studio/strategies">View all →</Link></Button>
        </div>
        <Card className="border-border bg-elevated">
          <div className="divide-y divide-border">
            {list.slice(0, 5).map((s) => (
              <Link key={s.id} to="/studio/strategy/$id" params={{ id: s.id }} className="grid grid-cols-12 items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/30">
                <div className="col-span-5">
                  <div className="font-medium">{s.name}</div>
                  <div className="text-xs text-muted-foreground">{s.description}</div>
                </div>
                <div className="col-span-2"><AssetClassBadge assetClass={s.assetClass} hideIcon /></div>
                <div className="col-span-3"><StageBadge stage={s.stage} /></div>
                <div className="col-span-2 text-right font-mono text-sm text-muted-foreground">
                  {s.stats ? `Sharpe ${s.stats.sharpe.toFixed(2)}` : "—"}
                </div>
              </Link>
            ))}
          </div>
        </Card>
      </section>
    </div>
  );
}
