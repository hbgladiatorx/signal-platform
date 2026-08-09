import { createFileRoute, useParams, notFound, Link } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getStrategyById, getStrategyEquity, getSignals,
  subscribeToStrategy, unsubscribeFromStrategy, useFollowedIds,
} from "@/lib/api";
import { checkSlotAvailability, isFreeStrategy } from "@/lib/api/billing";
import { PaywallModal } from "@/components/billing/PaywallModal";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { PipelineBadge } from "@/components/common/PipelineBadge";
import { OOSBadge, oosVerdict } from "@/components/common/OOSBadge";
import { DirectionPill } from "@/components/common/DirectionPill";
import { StatusPill } from "@/components/common/StatusPill";
import { Disclaimer } from "@/components/common/Disclaimer";
import { TradingViewChart } from "@/components/common/TradingViewChart";
import {
  Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { format } from "date-fns";
import { useState } from "react";

import { toast } from "sonner";


export const Route = createFileRoute("/app/strategy/$id")({
  head: ({ params }) => ({ meta: [{ title: `Strategy ${params.id} — Bayn` }] }),
  component: StrategyDetail,
});

function StrategyDetail() {
  const { id } = useParams({ from: "/app/strategy/$id" });
  const qc = useQueryClient();
  const followedIds = useFollowedIds();
  const isFollowed = followedIds.includes(id);
  const [paywallOpen, setPaywallOpen] = useState(false);
  const subscribe = useMutation({
    mutationFn: subscribeToStrategy,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["followed"] }); toast.success("Following — live signals will appear on Home"); },
  });
  const unsubscribe = useMutation({
    mutationFn: unsubscribeFromStrategy,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["followed"] }); toast("Unfollowed"); },
  });
  const toggleFollow = () => {
    if (isFollowed) { unsubscribe.mutate(id); return; }
    const check = checkSlotAvailability(id, followedIds.filter((x) => !isFreeStrategy(x)));
    if (check.ok) subscribe.mutate(id); else setPaywallOpen(true);
  };
  const strat = useQuery({ queryKey: ["strategy", id], queryFn: () => getStrategyById(id) });
  const equity = useQuery({ queryKey: ["equity", id], queryFn: () => getStrategyEquity(id, 90) });
  const sigs = useQuery({ queryKey: ["strat-sigs", id], queryFn: () => getSignals({ strategyId: id }) });

  if (strat.isFetched && !strat.data) throw notFound();
  const s = strat.data;
  if (!s) return <div className="p-6 text-muted-foreground">Loading…</div>;
  const primarySymbol = s.symbols?.[0];


  const ddData = (equity.data ?? []).reduce<{ t: string; dd: number; peak: number }[]>((acc, p) => {
    const peak = Math.max(p.equity, acc[acc.length - 1]?.peak ?? p.equity);
    acc.push({ t: p.t, dd: (p.equity - peak) / peak, peak });
    return acc;
  }, []);

  return (
    <div className="space-y-6 p-4 md:p-6">
      {/* hero */}
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2"><AssetClassBadge assetClass={s.assetClass} /> <PipelineBadge /> <OOSBadge strategy={s} /></div>
          <h1 className="text-3xl font-semibold tracking-tight">{s.name}</h1>
          <p className="max-w-2xl text-muted-foreground">{s.description}</p>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>by <span className="font-mono text-foreground">{s.devHandle}</span></span>
            <span>·</span><span>{s.stats.subscribers.toLocaleString()} subscribers</span>
            <span>·</span><span>Live {s.stats.liveDays} days</span>
          </div>
        </div>
        <Button onClick={toggleFollow}
          disabled={subscribe.isPending || unsubscribe.isPending}
          className={isFollowed ? "" : "bg-cyan text-cyan-foreground hover:bg-cyan/90"}
          variant={isFollowed ? "outline" : "default"} size="lg">
          {isFollowed ? "Following" : isFreeStrategy(id) ? "Follow" : "Subscribe · $99/mo"}
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Sharpe" value={s.stats.sharpe.toFixed(2)} accent="cyan" />
        <Stat label="Win rate" value={`${(s.stats.winRate * 100).toFixed(0)}%`} />
        <Stat label="Avg R" value={`${s.stats.avgR.toFixed(2)}R`} />
        <Stat label="Max DD" value={`${(s.stats.maxDrawdown * 100).toFixed(0)}%`} accent="danger" />
        <Stat label="Sample size" value={s.stats.sampleSize.toLocaleString()} />
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="backtest">Backtest</TabsTrigger>
          <TabsTrigger value="oos">Out-of-Sample</TabsTrigger>
          <TabsTrigger value="forward">Forward Test</TabsTrigger>
          <TabsTrigger value="signals">Recent Signals</TabsTrigger>
          <TabsTrigger value="dev">Developer</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4 pt-4">
          {primarySymbol && (
            <Card className="overflow-hidden border-border bg-elevated p-0">
              <TradingViewChart symbol={primarySymbol} assetClass={s.assetClass} interval="60" height={420} />
            </Card>
          )}
          <Card className="border-border bg-elevated p-5">
            <h3 className="mb-2 font-semibold">How it works</h3>
            <p className="text-sm text-muted-foreground">{s.longDescription}</p>
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Card className="border-border bg-elevated p-5">
              <h3 className="mb-2 font-semibold">Entry triggers</h3>
              <p className="text-sm text-muted-foreground">{s.entryRules}</p>
            </Card>
            <Card className="border-border bg-elevated p-5">
              <h3 className="mb-2 font-semibold">Exit rules</h3>
              <p className="text-sm text-muted-foreground">{s.exitRules}</p>
            </Card>
          </div>
        </TabsContent>


        <TabsContent value="backtest" className="space-y-4 pt-4">
          <ChartCard title="Equity curve (90D)" data={equity.data ?? []} dataKey="equity" gradient="cyan" />
          <ChartCard title="Drawdown" data={ddData} dataKey="dd" gradient="danger" tickFmt={(v) => `${(v * 100).toFixed(0)}%`} />
          <Card className="border-dashed border-border bg-elevated/50 p-8 text-center text-sm text-muted-foreground">
            Per-trade R-multiple distribution isn't available for this strategy yet.
          </Card>
        </TabsContent>

        <TabsContent value="oos" className="space-y-4 pt-4">
          <Card className="flex flex-col gap-2 border-border bg-elevated p-5">
            <div className="flex items-center gap-2">
              <OOSBadge strategy={s} />
              <span className="text-sm font-semibold">Out-of-sample validation</span>
            </div>
            <p className="text-sm text-muted-foreground">
              {oosVerdict(s) === "not-validated"
                ? "This strategy has no out-of-sample or forward results yet. Its edge has not been validated on held-out data."
                : "The win rate below is measured on data the strategy was not fit on (forward / walk-forward), so it reflects real out-of-sample performance."}
            </p>
          </Card>
          <div className="grid gap-3 md:grid-cols-3">
            <Stat
              label="OOS / Forward win rate"
              value={s.stats.winRate > 0 ? `${(s.stats.winRate * 100).toFixed(0)}%` : "Not available"}
            />
            <Stat label="Sample size" value={s.stats.sampleSize > 0 ? s.stats.sampleSize.toLocaleString() : "Not available"} />
            <Stat label="Max drawdown" value={s.stats.maxDrawdown > 0 ? `${(s.stats.maxDrawdown * 100).toFixed(0)}%` : "Not available"} accent="danger" />
          </div>
          {(equity.data ?? []).length > 0 && (
            <ChartCard title="Held-out period equity" data={(equity.data ?? []).slice(-45)} dataKey="equity" gradient="gold" />
          )}
        </TabsContent>

        <TabsContent value="forward" className="space-y-4 pt-4">
          {s.stats.liveDays > 0 ? (
            <div className="grid gap-3 md:grid-cols-3">
              <Stat label="Live days" value={s.stats.liveDays} accent="cyan" />
              <Stat label="Forward win rate" value={s.stats.winRate > 0 ? `${(s.stats.winRate * 100).toFixed(0)}%` : "Not available"} />
              <Stat label="Subscribers" value={s.stats.subscribers.toLocaleString()} />
            </div>
          ) : (
            <Card className="border-dashed border-border bg-elevated/50 p-8 text-center text-sm text-muted-foreground">
              This strategy isn't live yet, so there's no forward-tracked performance to show.
            </Card>
          )}
          {s.stats.liveDays > 0 && (equity.data ?? []).length > 0 && (
            <ChartCard title="Forward equity" data={(equity.data ?? []).slice(-30)} dataKey="equity" gradient="cyan" />
          )}
          <Disclaimer variant="inline" />
        </TabsContent>

        <TabsContent value="signals" className="space-y-4 pt-4">
          {primarySymbol && (
            <Card className="overflow-hidden border-border bg-elevated p-0">
              <TradingViewChart symbol={primarySymbol} assetClass={s.assetClass} interval="60" height={360} />
            </Card>
          )}

          <Card className="border-border bg-elevated">
            <div className="divide-y divide-border">
              {(sigs.data ?? []).slice(0, 20).map((sig) => (
                <Link key={sig.id} to="/app/signal/$id" params={{ id: sig.id }} className="grid grid-cols-12 items-center gap-3 px-4 py-3 text-sm hover:bg-muted/30">
                  <div className="col-span-3 text-xs text-muted-foreground">{format(new Date(sig.firedAt), "MMM d, HH:mm")}</div>
                  <div className="col-span-2 font-mono">{sig.symbol}</div>
                  <div className="col-span-1"><DirectionPill direction={sig.direction} /></div>
                  <div className="col-span-4 font-mono text-xs text-muted-foreground">
                    {sig.entry} / stop {sig.stop} / tgt {sig.target}
                  </div>
                  <div className="col-span-1"><StatusPill status={sig.status} /></div>
                  <div className="col-span-1 text-right font-mono text-sm">
                    {sig.pnlR != null ? <span className={sig.pnlR >= 0 ? "text-cyan" : "text-danger"}>{sig.pnlR.toFixed(2)}R</span> : "—"}
                  </div>
                </Link>
              ))}
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="dev" className="pt-4">
          <Card className="border-border bg-elevated p-5">
            <div className="flex items-center gap-3">
              <div className="grid size-12 place-items-center rounded-full bg-cyan/15 font-mono text-cyan">{s.devHandle.slice(1, 3).toUpperCase()}</div>
              <div>
                <div className="font-mono text-lg">{s.devHandle}</div>
                <div className="text-xs text-muted-foreground">Joined {format(new Date(s.createdAt), "MMM yyyy")}</div>
              </div>
            </div>
          </Card>
        </TabsContent>
      </Tabs>

      <PaywallModal
        strategyId={paywallOpen ? id : null}
        open={paywallOpen}
        onOpenChange={setPaywallOpen}
        onResolved={() => { qc.invalidateQueries({ queryKey: ["followed"] }); setPaywallOpen(false); }}
      />
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: React.ReactNode; accent?: "cyan" | "danger" }) {
  return (
    <Card className="border-border bg-elevated p-4">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-2xl ${accent === "cyan" ? "text-cyan" : accent === "danger" ? "text-danger" : ""}`}>{value}</div>
    </Card>
  );
}

function ChartCard({ title, data, dataKey, gradient, tickFmt }: { title: string; data: any[]; dataKey: string; gradient: "cyan" | "danger" | "gold"; tickFmt?: (v: number) => string }) {
  const colorVar = gradient === "cyan" ? "var(--cyan)" : gradient === "danger" ? "var(--danger)" : "var(--gold)";
  const id = `g-${gradient}-${dataKey}`;
  return (
    <Card className="border-border bg-elevated p-4">
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colorVar} stopOpacity={0.4} />
                <stop offset="100%" stopColor={colorVar} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
            <XAxis dataKey="t" tickFormatter={(v) => format(new Date(v), "MMM d")} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} tickFormatter={tickFmt} />
            <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
            <Area type="monotone" dataKey={dataKey} stroke={colorVar} strokeWidth={2} fill={`url(#${id})`} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
