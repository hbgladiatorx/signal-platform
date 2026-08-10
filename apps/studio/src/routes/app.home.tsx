import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getSignals, getUserPerformance, useFollowedIds } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DirectionPill } from "@/components/common/DirectionPill";
import { StatusPill } from "@/components/common/StatusPill";
import { LiveTrackerChart } from "@/components/common/LiveTrackerChart";
import { CustomizeButton } from "@/components/common/CustomizeButton";
import { NextStep } from "@/components/common/NextStep";
import { MetricLabel } from "@/components/common/Term";
import { useAssetFilter } from "@/lib/asset-filter";
import { formatDistanceToNow } from "date-fns";
import { ArrowRight, BarChart3, LineChart } from "lucide-react";

export const Route = createFileRoute("/app/home")({
  head: () => ({ meta: [{ title: "Today — Bayn" }] }),
  component: HomePage,
});

const fmtPct = (n: number) => `${(n * 100).toFixed(0)}%`;

function HomePage() {
  const { assetClass } = useAssetFilter();
  const followed = useFollowedIds();
  const followedSet = useMemo(() => new Set(followed), [followed]);

  const recent = useQuery({ queryKey: ["recent"], queryFn: () => getSignals({ limit: 30 }) });
  const perf = useQuery({ queryKey: ["perf", 30], queryFn: () => getUserPerformance(30) });

  // Only signals that need attention: OPEN, from a strategy you follow.
  const openSignals = useMemo(() => {
    return (recent.data ?? [])
      .filter((s) => followedSet.has(s.strategyId) && s.status === "OPEN")
      .filter((s) => assetClass === "all" || s.assetClass === assetClass)
      .slice(0, 4);
  }, [recent.data, followedSet, assetClass]);

  const k = perf.data?.kpis;

  return (
    <div className="mx-auto max-w-4xl space-y-8 p-4 md:p-8">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Today</h1>
          <p className="text-sm text-muted-foreground">Your one place to see what needs doing.</p>
        </div>
        <CustomizeButton mode="trader" />
      </div>

      {/* 1 — the single next action */}
      <NextStep />

      {/* 2 — needs your attention: open signals */}
      {openSignals.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium uppercase tracking-[0.16em] text-muted-foreground">Needs your attention</h2>
            <Button variant="ghost" size="sm" asChild><Link to="/app/signals">All signals <ArrowRight className="ml-1 size-3.5" /></Link></Button>
          </div>
          <Card className="divide-y divide-border border-border bg-elevated">
            {openSignals.map((sig) => (
              <Link
                key={sig.id}
                to="/app/signal/$id"
                params={{ id: sig.id }}
                className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-muted/30"
              >
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-cyan/10 text-cyan">
                  <LineChart className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{sig.symbol} · {sig.strategyName}</div>
                  <div className="text-xs text-muted-foreground">Fired {formatDistanceToNow(new Date(sig.firedAt), { addSuffix: true })}</div>
                </div>
                <DirectionPill direction={sig.direction} />
                <StatusPill status={sig.status} />
                <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
              </Link>
            ))}
          </Card>
        </section>
      )}

      {/* 3 — one live chart (your top signal, or a watchlist ticker) */}
      <section className="space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-[0.16em] text-muted-foreground">Live tracking</h2>
        <LiveTrackerChart />
      </section>

      {/* 4 — compact performance snapshot */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium uppercase tracking-[0.16em] text-muted-foreground">Your snapshot · 30d</h2>
          <Button variant="ghost" size="sm" asChild><Link to="/app/performance">Full performance <ArrowRight className="ml-1 size-3.5" /></Link></Button>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Kpi label={<MetricLabel term="winRate" />} value={k ? fmtPct(k.winRate) : "—"} accent="cyan" />
          <Kpi label={<MetricLabel term="avgR">Avg R</MetricLabel>} value={k ? `${k.avgR.toFixed(2)}R` : "—"} />
          <Kpi label={<MetricLabel term="signal">Taken</MetricLabel>} value={k?.totalTaken ?? "—"} />
        </div>
      </section>

      {/* 5 — everything non-urgent, one tap away */}
      <Link
        to="/app/markets"
        className="flex items-center gap-3 rounded-xl border border-border bg-elevated/60 p-4 transition-colors hover:border-cyan/30 hover:bg-elevated"
      >
        <span className="grid size-9 place-items-center rounded-lg bg-muted/40 text-muted-foreground"><BarChart3 className="size-4" /></span>
        <div className="flex-1">
          <div className="text-sm font-medium">Markets &amp; news</div>
          <div className="text-xs text-muted-foreground">Market overview and your news wire.</div>
        </div>
        <ArrowRight className="size-4 text-muted-foreground" />
      </Link>
    </div>
  );
}

function Kpi({ label, value, accent }: { label: React.ReactNode; value: React.ReactNode; accent?: "cyan" }) {
  return (
    <Card className="border-border bg-elevated p-4">
      <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-2xl ${accent === "cyan" ? "text-cyan" : ""}`}>{value}</div>
    </Card>
  );
}
