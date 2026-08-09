import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getDevStrategies, getRecentBacktests } from "@/lib/api/studio";
import { listSessions } from "@/lib/api/sessions";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StageBadge } from "@/components/common/StageBadge";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { formatDistanceToNow } from "date-fns";
import { Plus, Layers, FlaskConical, Activity, Inbox, TrendingUp, Trophy, PencilRuler, Rocket, Send } from "lucide-react";
import { CustomizeButton } from "@/components/common/CustomizeButton";
import { cn } from "@/lib/utils";
import type { PipelineStage } from "@/lib/types";

export const Route = createFileRoute("/studio/home")({
  head: () => ({ meta: [{ title: "Overview — Bayn Studio" }] }),
  component: StudioHome,
});

// Pipeline status cards. Each links to /studio/strategies?stage=<PipelineStage>,
// which the list reads on load (absent => "All stages").
const STAGE_CARDS: Array<{
  label: string;
  stage: PipelineStage;
  icon: typeof Layers;
  accent: string;
}> = [
  { label: "Draft", stage: "Draft", icon: PencilRuler, accent: "text-muted-foreground" },
  { label: "Backtesting", stage: "Backtested", icon: FlaskConical, accent: "text-cyan" },
  { label: "Forward-testing", stage: "Forward Testing", icon: Activity, accent: "text-futures" },
  { label: "Live", stage: "Live", icon: Rocket, accent: "text-emerald-500" },
  { label: "Submitted", stage: "Submitted", icon: Send, accent: "text-violet" },
];

const fmtPct = (v?: number) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
const pctClass = (v?: number) =>
  v == null ? "text-muted-foreground" : v >= 0 ? "text-emerald-500" : "text-red-500";
const tickerOf = (sym: string) => sym.split("@")[0];

function StudioHome() {
  const strategies = useQuery({ queryKey: ["devStrategies"], queryFn: getDevStrategies });
  const backtests = useQuery({ queryKey: ["recentBacktests", 12], queryFn: () => getRecentBacktests(12) });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: listSessions, refetchInterval: 15000 });

  const list = strategies.data ?? [];
  const runs = backtests.data ?? [];
  const sess = sessions.data ?? [];

  const summary = useMemo(() => {
    const withStats = list.filter((s) => s.stats);
    const returns = withStats.map((s) => s.stats!.totalReturn).filter((v): v is number => v != null);
    const best = withStats
      .filter((s) => s.stats!.totalReturn != null)
      .sort((a, b) => (b.stats!.totalReturn ?? 0) - (a.stats!.totalReturn ?? 0))[0];
    const liveCount = sess.filter((s) => s.status === "running" || s.status === "starting").length;
    return {
      total: list.length,
      backtested: withStats.length,
      sessions: sess.length,
      liveCount,
      bestReturn: returns.length ? Math.max(...returns) : undefined,
      best,
    };
  }, [list, sess]);

  const topStrategies = useMemo(
    () =>
      [...list].sort(
        (a, b) => (b.stats?.totalReturn ?? -Infinity) - (a.stats?.totalReturn ?? -Infinity),
      ),
    [list],
  );

  const tiles: Array<{
    label: string;
    value: string;
    sub?: string;
    valueClass?: string;
    icon: typeof Layers;
    accent: string;
  }> = [
    { label: "Strategies", value: String(summary.total), icon: Layers, accent: "text-violet" },
    { label: "Backtested", value: String(summary.backtested), icon: FlaskConical, accent: "text-cyan" },
    { label: "Live / paper", value: String(summary.sessions), sub: summary.liveCount ? `${summary.liveCount} running` : undefined, icon: Activity, accent: "text-futures" },
    { label: "Best return", value: fmtPct(summary.bestReturn), valueClass: pctClass(summary.bestReturn), icon: TrendingUp, accent: "text-emerald-500" },
    { label: "Backtests run", value: String(runs.length >= 12 ? "12+" : runs.length), icon: Trophy, accent: "text-gold" },
  ];

  return (
    <div className="space-y-6 p-4 md:p-6">
      {/* Hero */}
      <div
        className="relative overflow-hidden rounded-xl border border-violet/30 p-5"
        style={{ background: "linear-gradient(135deg, color-mix(in oklab, var(--violet) 14%, var(--background)) 0%, var(--background) 65%)" }}
      >
        <div className="pointer-events-none absolute -right-16 -top-16 size-48 rounded-full bg-violet/20 blur-3xl" />
        <div className="relative flex flex-wrap items-end justify-between gap-3">
          <div className="space-y-1.5">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-violet/40 bg-violet/10 px-2 py-0.5 text-[10px] font-mono uppercase tracking-[0.18em] text-violet">
              Overview
            </span>
            <h1 className="text-2xl font-semibold tracking-tight">My Studio</h1>
            <p className="font-mono text-xs text-muted-foreground">
              // everything at a glance — strategies, backtests, and live trading
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
        {summary.best && (
          <div className="relative mt-4 inline-flex items-center gap-2 rounded-lg border border-border bg-background/50 px-3 py-1.5 text-xs">
            <Trophy className="size-3.5 text-gold" />
            <span className="text-muted-foreground">Top performer:</span>
            <Link to="/studio/strategy/$id" params={{ id: summary.best.id }} className="font-medium hover:text-violet">{summary.best.name}</Link>
            <span className={cn("font-mono", pctClass(summary.best.stats?.totalReturn))}>{fmtPct(summary.best.stats?.totalReturn)}</span>
            {summary.best.stats?.profitFactor != null && <span className="font-mono text-muted-foreground">PF {summary.best.stats.profitFactor.toFixed(2)}</span>}
          </div>
        )}
      </div>

      {/* Summary tiles */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {tiles.map((t) => (
          <Card key={t.label} className="border-border bg-elevated p-4 transition-colors hover:border-violet/30">
            <div className="flex items-center justify-between">
              <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">{t.label}</div>
              <t.icon className={cn("size-3.5", t.accent)} />
            </div>
            <div className={cn("mt-1 font-mono text-3xl tabular-nums", t.valueClass)}>{t.value}</div>
            {t.sub && <div className="font-mono text-[10px] text-futures">{t.sub}</div>}
          </Card>
        ))}
      </div>

      {/* Pipeline status — each card opens the strategy list pre-filtered */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {STAGE_CARDS.map((c) => {
          const count = list.filter((s) => s.stage === c.stage).length;
          return (
            <Link
              key={c.stage}
              to="/studio/strategies"
              search={{ stage: c.stage }}
              className="block"
            >
              <Card className="h-full border-border bg-elevated p-4 transition-colors hover:border-violet/40">
                <div className="flex items-center justify-between">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">{c.label}</div>
                  <c.icon className={cn("size-3.5", c.accent)} />
                </div>
                <div className="mt-1 font-mono text-3xl tabular-nums">{count}</div>
                <div className="font-mono text-[10px] text-muted-foreground">View →</div>
              </Card>
            </Link>
          );
        })}
      </div>

      {/* Live sessions + Recent backtests */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Live / paper sessions */}
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-medium uppercase tracking-wider text-muted-foreground"><Activity className="size-4" /> Live & paper</h2>
            <Button variant="ghost" size="sm" asChild><Link to="/studio/live">Monitor →</Link></Button>
          </div>
          <Card className="border-border bg-elevated">
            {sess.length === 0 ? (
              <div className="p-6 text-center text-sm text-muted-foreground">
                <Inbox className="mx-auto mb-2 size-8 opacity-50" />
                No live or paper sessions running. Deploy a strategy to start trading.
              </div>
            ) : (
              <div className="divide-y divide-border">
                {sess.slice(0, 6).map((s) => {
                  const pnl = s.realized_pnl == null ? undefined : Number(s.realized_pnl);
                  return (
                    <div key={s.id} className="grid grid-cols-12 items-center gap-2 px-4 py-3 text-sm">
                      <div className="col-span-5 truncate">
                        <div className="truncate font-medium">{s.strategy_name}</div>
                        <div className="font-mono text-[11px] text-muted-foreground">{s.symbols.map(tickerOf).join(", ")}</div>
                      </div>
                      <div className="col-span-2">
                        <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-mono uppercase", s.mode === "live" ? "bg-red-500/15 text-red-500" : "bg-cyan/15 text-cyan")}>{s.mode}</span>
                      </div>
                      <div className="col-span-2 font-mono text-[11px] text-muted-foreground">{s.status}</div>
                      <div className={cn("col-span-3 text-right font-mono text-xs", pnl == null ? "text-muted-foreground" : pnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                        {pnl == null ? "—" : `${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}`}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </section>

        {/* Recent backtests */}
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-medium uppercase tracking-wider text-muted-foreground"><FlaskConical className="size-4" /> Recent backtests</h2>
            <Button variant="ghost" size="sm" asChild><Link to="/studio/backtests">View all →</Link></Button>
          </div>
          <Card className="border-border bg-elevated">
            {runs.length === 0 ? (
              <div className="p-6 text-center text-sm text-muted-foreground">
                <Inbox className="mx-auto mb-2 size-8 opacity-50" />
                No backtests yet. Run one from a strategy to see it here.
              </div>
            ) : (
              <div className="divide-y divide-border">
                {runs.slice(0, 6).map((b) => (
                  <div key={b.id} className="grid grid-cols-12 items-center gap-2 px-4 py-3 text-sm">
                    <div className="col-span-5 truncate">
                      <div className="truncate font-medium">{b.strategyName}</div>
                      <div className="font-mono text-[11px] text-muted-foreground">{b.symbols.map(tickerOf).join(", ")} · {formatDistanceToNow(new Date(b.createdAt), { addSuffix: true })}</div>
                    </div>
                    <div className={cn("col-span-3 text-right font-mono", pctClass(b.totalReturn))}>
                      {b.status === "completed" ? fmtPct(b.totalReturn) : <span className="text-muted-foreground">{b.status}</span>}
                    </div>
                    <div className="col-span-2 text-right font-mono text-xs text-muted-foreground">{b.sharpe != null ? `Sh ${b.sharpe.toFixed(2)}` : "—"}</div>
                    <div className="col-span-2 text-right font-mono text-xs text-muted-foreground">{b.trades ?? "—"} trd</div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </section>
      </div>

      {/* Strategies overview — full metrics */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-medium uppercase tracking-wider text-muted-foreground"><Layers className="size-4" /> Strategies</h2>
          <Button variant="ghost" size="sm" asChild><Link to="/studio/strategies">View all →</Link></Button>
        </div>
        <Card className="border-border bg-elevated">
          <div className="grid grid-cols-12 gap-2 border-b border-border px-4 py-2 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            <div className="col-span-3">Name</div>
            <div className="col-span-1">Asset</div>
            <div className="col-span-2">Status</div>
            <div className="col-span-1 text-right">Return</div>
            <div className="col-span-1 text-right">PF</div>
            <div className="col-span-1 text-right">Sharpe</div>
            <div className="col-span-1 text-right">Win</div>
            <div className="col-span-1 text-right">Max DD</div>
            <div className="col-span-1 text-right">Trades</div>
          </div>
          {topStrategies.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">No strategies yet. Build one to get started.</div>
          ) : (
            <div className="divide-y divide-border">
              {topStrategies.slice(0, 10).map((s) => {
                const st = s.stats;
                return (
                  <Link key={s.id} to="/studio/strategy/$id" params={{ id: s.id }} className="grid grid-cols-12 items-center gap-2 px-4 py-3 text-sm transition-colors hover:bg-muted/30">
                    <div className="col-span-3 truncate font-medium">{s.name}</div>
                    <div className="col-span-1"><AssetClassBadge assetClass={s.assetClass} hideIcon /></div>
                    <div className="col-span-2"><StageBadge stage={s.stage} /></div>
                    <div className={cn("col-span-1 text-right font-mono", pctClass(st?.totalReturn))}>{st?.totalReturn != null ? fmtPct(st.totalReturn) : "—"}</div>
                    <div className="col-span-1 text-right font-mono">{st?.profitFactor != null ? st.profitFactor.toFixed(2) : "—"}</div>
                    <div className="col-span-1 text-right font-mono">{st?.sharpe != null ? st.sharpe.toFixed(2) : "—"}</div>
                    <div className="col-span-1 text-right font-mono">{st ? `${(st.winRate * 100).toFixed(0)}%` : "—"}</div>
                    <div className="col-span-1 text-right font-mono text-muted-foreground">{st ? `${(st.maxDrawdown * 100).toFixed(0)}%` : "—"}</div>
                    <div className="col-span-1 text-right font-mono text-muted-foreground">{st?.totalTrades ?? "—"}</div>
                  </Link>
                );
              })}
            </div>
          )}
        </Card>
      </section>
    </div>
  );
}
