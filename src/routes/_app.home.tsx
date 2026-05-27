import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  getFollowedStrategies, getMarketOverview, getRecentSignals, getUserPerformance,
} from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { DirectionPill } from "@/components/common/DirectionPill";
import { StatusPill } from "@/components/common/StatusPill";
import { Sparkline } from "@/components/common/Sparkline";
import { PipelineBadge } from "@/components/common/PipelineBadge";
import { formatDistanceToNow } from "date-fns";
import { useState } from "react";
import {
  Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { TrendingUp, Inbox } from "lucide-react";

export const Route = createFileRoute("/_app/home")({
  head: () => ({ meta: [{ title: "Home — Bayn" }] }),
  component: HomePage,
});

const fmtMoney = (n: number) => n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: n > 1000 ? 0 : 2 });
const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${(n * 100).toFixed(2)}%`;

function HomePage() {
  const [days, setDays] = useState(30);
  const market = useQuery({ queryKey: ["market"], queryFn: getMarketOverview });
  const followed = useQuery({ queryKey: ["followed"], queryFn: getFollowedStrategies });
  const recent = useQuery({ queryKey: ["recent"], queryFn: () => getRecentSignals(10) });
  const perf = useQuery({ queryKey: ["perf", days], queryFn: () => getUserPerformance(days) });

  return (
    <div className="space-y-8 p-4 md:p-6">
      {/* Market overview */}
      <section>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-muted-foreground">Market overview</h2>
        <div className="flex gap-3 overflow-x-auto pb-2">
          {(market.data ?? Array.from({ length: 6 })).map((tile: any, i: number) => (
            <Card key={tile?.symbol ?? i} className="flex w-56 shrink-0 flex-col gap-2 border-border bg-elevated p-4">
              {tile ? (
                <>
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="font-semibold">{tile.symbol}</div>
                      <div className="text-xs text-muted-foreground">{tile.label}</div>
                    </div>
                    <div className={tile.changePct >= 0 ? "text-cyan" : "text-danger"}>
                      <div className="text-right font-mono text-sm">{fmtMoney(tile.price)}</div>
                      <div className="text-right text-xs">{fmtPct(tile.changePct / 100)}</div>
                    </div>
                  </div>
                  <div className="h-10">
                    <Sparkline data={tile.spark} positive={tile.changePct >= 0} />
                  </div>
                </>
              ) : <div className="h-20 animate-pulse rounded bg-muted/50" />}
            </Card>
          ))}
        </div>
      </section>

      {/* My strategies */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">My strategies</h2>
          <Button variant="ghost" size="sm" asChild><Link to="/catalog">Browse catalog →</Link></Button>
        </div>
        {followed.data?.length === 0 ? (
          <EmptyState icon={Inbox} title="You're not following any strategies yet" cta={<Button asChild><Link to="/catalog">Explore catalog</Link></Button>} />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
            {(followed.data ?? []).map((s) => (
              <Link key={s.id} to="/strategy/$id" params={{ id: s.id }}>
                <Card className="group h-full border-border bg-elevated p-4 transition-colors hover:border-cyan/30">
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <h3 className="font-semibold leading-tight group-hover:text-cyan">{s.name}</h3>
                    <AssetClassBadge assetClass={s.assetClass} hideIcon />
                  </div>
                  <p className="mb-3 text-xs text-muted-foreground line-clamp-2">{s.description}</p>
                  <div className="mb-3 flex items-center gap-2">
                    <StatusChip status={s.status} />
                    <span className="text-xs text-muted-foreground">
                      Signal {formatDistanceToNow(new Date(s.lastSignalAt), { addSuffix: true })}
                    </span>
                  </div>
                  <div className="flex items-end justify-between text-xs">
                    <div>
                      <div className="font-mono text-lg text-foreground">{(s.stats.winRate * 100).toFixed(0)}%</div>
                      <div className="text-muted-foreground">Win rate · {s.stats.sampleSize} trades</div>
                    </div>
                    <PipelineBadge compact />
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* Recent signals */}
      <section>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-muted-foreground">Recent signals</h2>
        <Card className="border-border bg-elevated">
          <div className="divide-y divide-border">
            {(recent.data ?? []).map((sig) => (
              <Link key={sig.id} to="/signal/$id" params={{ id: sig.id }} className="grid grid-cols-12 items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/30">
                <div className="col-span-2 text-xs text-muted-foreground">
                  {formatDistanceToNow(new Date(sig.firedAt), { addSuffix: true })}
                </div>
                <div className="col-span-3 truncate">
                  <div className="truncate text-sm font-medium">{sig.strategyName}</div>
                  <div className="text-xs text-muted-foreground">{sig.symbol}</div>
                </div>
                <div className="col-span-1"><DirectionPill direction={sig.direction} /></div>
                <div className="col-span-3 font-mono text-xs text-muted-foreground">
                  <span className="text-foreground">{sig.entry}</span> · stop {sig.stop} · tgt {sig.target}
                </div>
                <div className="col-span-1"><StatusPill status={sig.status} /></div>
                <div className="col-span-2 h-8">
                  <Sparkline data={sig.priceSeries.slice(-30).map((p) => p.price)} positive={sig.direction === "LONG"} />
                </div>
              </Link>
            ))}
            {!recent.data && Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-12 animate-pulse bg-muted/20" />
            ))}
          </div>
        </Card>
      </section>

      {/* Performance */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">My performance</h2>
          <Tabs value={String(days)} onValueChange={(v) => setDays(Number(v))}>
            <TabsList>
              {[7, 30, 90, 365].map((d) => (
                <TabsTrigger key={d} value={String(d)}>{d === 365 ? "All" : `${d}D`}</TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
        <Card className="border-border bg-elevated p-4">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={perf.data?.equity ?? []}>
                <defs>
                  <linearGradient id="eqg" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--cyan)" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="var(--cyan)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
                <XAxis dataKey="t" tickFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: "short", day: "numeric" })} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} labelFormatter={(v) => new Date(v).toLocaleString()} formatter={(v: number) => fmtMoney(v)} />
                <Area type="monotone" dataKey="equity" stroke="var(--cyan)" strokeWidth={2} fill="url(#eqg)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Total signals taken" value={perf.data?.kpis.totalTaken ?? "—"} />
            <Kpi label="Win rate" value={perf.data ? `${(perf.data.kpis.winRate * 100).toFixed(0)}%` : "—"} accent="cyan" />
            <Kpi label="Avg R-multiple" value={perf.data ? perf.data.kpis.avgR.toFixed(2) + "R" : "—"} />
            <Kpi label="Max drawdown" value={perf.data ? fmtPct(perf.data.kpis.maxDrawdown) : "—"} accent="danger" />
          </div>
        </Card>
      </section>
    </div>
  );
}

function Kpi({ label, value, accent }: { label: string; value: React.ReactNode; accent?: "cyan" | "danger" }) {
  return (
    <div className="rounded-lg border border-border bg-background/40 p-3">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-2xl ${accent === "cyan" ? "text-cyan" : accent === "danger" ? "text-danger" : ""}`}>
        {value}
      </div>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  const c = status === "In Position" ? "text-cyan border-cyan/30 bg-cyan/10"
          : status === "Cooldown"    ? "text-muted-foreground border-border bg-muted/30"
                                     : "text-gold border-gold/30 bg-gold/10";
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${c}`}>{status}</span>;
}

function EmptyState({ icon: Icon, title, cta }: { icon: typeof TrendingUp; title: string; cta?: React.ReactNode }) {
  return (
    <Card className="grid place-items-center gap-3 border-dashed border-border bg-elevated/40 p-10 text-center">
      <Icon className="size-8 text-muted-foreground" />
      <div className="text-sm text-muted-foreground">{title}</div>
      {cta}
    </Card>
  );
}
