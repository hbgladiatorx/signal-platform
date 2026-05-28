import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { getUserPerformance } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatusPill } from "@/components/common/StatusPill";
import { DirectionPill } from "@/components/common/DirectionPill";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import {
  Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { Download, Share2 } from "lucide-react";
import { format } from "date-fns";
import { useAssetFilter } from "@/lib/asset-filter";

export const Route = createFileRoute("/app/performance")({
  head: () => ({ meta: [{ title: "Performance — Bayn" }] }),
  component: PerformancePage,
});

function PerformancePage() {
  const [days, setDays] = useState(90);
  const { assetClass } = useAssetFilter();
  const { data } = useQuery({ queryKey: ["perf-full", days], queryFn: () => getUserPerformance(days) });

  const taken = useMemo(() => {
    const all = data?.taken ?? [];
    return assetClass === "all" ? all : all.filter((t) => t.signal.assetClass === assetClass);
  }, [data, assetClass]);

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Performance {assetClass !== "all" && <span className="text-muted-foreground">· {assetClass}</span>}
          </h1>
          <p className="text-sm text-muted-foreground">Outcomes of every signal you've taken — measured honestly.</p>
        </div>
        <Tabs value={String(days)} onValueChange={(v) => setDays(Number(v))}>
          <TabsList>
            {[7, 30, 90, 365].map((d) => (
              <TabsTrigger key={d} value={String(d)}>{d === 365 ? "All" : `${d}D`}</TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Kpi label="Signals taken" value={data?.kpis.totalTaken ?? "—"} />
        <Kpi label="Win rate" value={data ? `${(data.kpis.winRate * 100).toFixed(0)}%` : "—"} tone="cyan" />
        <Kpi label="Avg R" value={data ? `${data.kpis.avgR.toFixed(2)}R` : "—"} />
        <Kpi label="Max drawdown" value={data ? `${(data.kpis.maxDrawdown * 100).toFixed(2)}%` : "—"} tone="danger" />
      </div>


      <Card className="border-border bg-elevated p-4">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data?.equity ?? []}>
              <defs>
                <linearGradient id="pg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--cyan)" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="var(--cyan)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
              <XAxis dataKey="t" tickFormatter={(v) => format(new Date(v), "MMM d")} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} labelFormatter={(v) => format(new Date(v), "PP")} />
              <Area type="monotone" dataKey="equity" stroke="var(--cyan)" strokeWidth={2} fill="url(#pg)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card className="border-border bg-elevated">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Taken signals {assetClass !== "all" && <span className="text-muted-foreground">· {assetClass}</span>}</h2>
          <div className="flex gap-2">
            <Button asChild variant="outline" size="sm">
              <Link to="/app/share/$cardId" params={{ cardId: `perf-${days}` }}>
                <Share2 className="mr-2 size-3.5" /> Share summary
              </Link>
            </Button>
            <Button variant="outline" size="sm"><Download className="mr-2 size-3.5" /> Export CSV</Button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-muted-foreground">
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left font-medium">Date</th>
                <th className="px-4 py-2 text-left font-medium">Strategy</th>
                <th className="px-4 py-2 text-left font-medium">Symbol</th>
                <th className="px-4 py-2 text-left font-medium">Dir</th>
                <th className="px-4 py-2 text-right font-medium">Entry</th>
                <th className="px-4 py-2 text-right font-medium">Fill</th>
                <th className="px-4 py-2 text-right font-medium">R</th>
                <th className="px-4 py-2 text-left font-medium">Result</th>
                <th className="px-4 py-2 text-right font-medium">Share</th>
              </tr>
            </thead>
            <tbody>
              {taken.map((t) => (
                <tr key={t.id} className="border-b border-border/60 hover:bg-muted/30">
                  <td className="px-4 py-2 text-muted-foreground">{format(new Date(t.takenAt), "MMM d, HH:mm")}</td>
                  <td className="px-4 py-2"><div className="flex items-center gap-2"><AssetClassBadge assetClass={t.signal.assetClass} hideIcon /> <span className="truncate">{t.signal.strategyName}</span></div></td>
                  <td className="px-4 py-2 font-mono">{t.signal.symbol}</td>
                  <td className="px-4 py-2"><DirectionPill direction={t.signal.direction} /></td>
                  <td className="px-4 py-2 text-right font-mono">{t.signal.entry}</td>
                  <td className="px-4 py-2 text-right font-mono">{t.fillPrice}</td>
                  <td className={`px-4 py-2 text-right font-mono ${(t.pnlR ?? 0) >= 0 ? "text-cyan" : "text-danger"}`}>{t.pnlR?.toFixed(2)}R</td>
                  <td className="px-4 py-2"><StatusPill status={t.outcome} /></td>
                  <td className="px-4 py-2 text-right">
                    <Button asChild size="icon" variant="ghost" className="size-7">
                      <Link to="/app/share/$cardId" params={{ cardId: t.signal.id }}>
                        <Share2 className="size-3.5" />
                      </Link>
                    </Button>
                  </td>
                </tr>
              ))}
              {taken.length === 0 && (
                <tr><td colSpan={9} className="px-4 py-10 text-center text-sm text-muted-foreground">
                  No taken {assetClass !== "all" ? assetClass + " " : ""}signals in this period.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
