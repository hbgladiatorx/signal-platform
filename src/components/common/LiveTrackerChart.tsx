import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { getFollowedStrategies, getSignals } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Activity, ArrowUpRight } from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useAssetFilter } from "@/lib/asset-filter";
import { DirectionPill } from "./DirectionPill";
import { cn } from "@/lib/utils";

const fmt = (n: number) =>
  n >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 2 })
            : n.toLocaleString(undefined, { maximumFractionDigits: 2 });

/** Hero chart that tracks the live signal(s) from the user's followed strategies.
 *  Shows entry / stop / target reference lines and a widget badge for the strategy. */
export function LiveTrackerChart() {
  const { assetClass } = useAssetFilter();
  const followed = useQuery({ queryKey: ["followed"], queryFn: getFollowedStrategies });
  const signals = useQuery({ queryKey: ["recent"], queryFn: () => getSignals({ limit: 30 }) });

  const candidates = useMemo(() => {
    const followedIds = new Set((followed.data ?? []).map((s) => s.id));
    return (signals.data ?? [])
      .filter((s) => followedIds.has(s.strategyId))
      .filter((s) => assetClass === "all" || s.assetClass === assetClass)
      .slice(0, 4);
  }, [followed.data, signals.data, assetClass]);

  const [activeId, setActiveId] = useState<string | null>(null);
  const active = candidates.find((c) => c.id === activeId) ?? candidates[0];

  if (!active) {
    return (
      <Card className="border-dashed border-border bg-elevated/40 p-8 text-center">
        <Activity className="mx-auto mb-3 size-6 text-muted-foreground" />
        <div className="text-sm text-muted-foreground">
          Follow a strategy from the catalog to see its live tracking chart here.
        </div>
        <Button asChild className="mt-4 bg-cyan text-cyan-foreground hover:bg-cyan/90">
          <Link to="/app/catalog">Browse catalog</Link>
        </Button>
      </Card>
    );
  }

  const series = active.priceSeries;
  const last = series[series.length - 1]?.price ?? active.entry;
  const isLong = active.direction === "LONG";
  const inWinDir = isLong ? last >= active.entry : last <= active.entry;
  const distToTarget = Math.abs((active.target - last) / last) * 100;
  const distToStop = Math.abs((active.stop - last) / last) * 100;

  return (
    <Card className="overflow-hidden border-border bg-elevated">
      {/* Header strip */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background/40 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="grid size-9 place-items-center rounded-md border border-cyan/30 bg-cyan/10">
            <Activity className="size-4 text-cyan" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="pulse-dot text-[10px] font-mono uppercase tracking-[0.18em] text-cyan">Live</span>
              <span className="rounded-sm bg-muted/40 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                Tracking strategy
              </span>
            </div>
            <Link
              to="/app/strategy/$id"
              params={{ id: active.strategyId }}
              className="block truncate text-sm font-semibold leading-tight hover:text-cyan"
            >
              {active.strategyName}
            </Link>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-4 font-mono text-xs">
          <Kv label="Symbol" value={active.symbol} />
          <DirectionPill direction={active.direction} />
          <Kv label="Last" value={fmt(last)} tone={inWinDir ? "pos" : "neg"} />
          <Kv label="To target" value={`${distToTarget.toFixed(2)}%`} tone="pos" />
          <Kv label="To stop" value={`${distToStop.toFixed(2)}%`} tone="neg" />
          <Button asChild variant="ghost" size="sm" className="h-7 gap-1 text-cyan">
            <Link to="/app/signal/$id" params={{ id: active.id }}>
              Open <ArrowUpRight className="size-3.5" />
            </Link>
          </Button>
        </div>
      </div>

      {/* Chart */}
      <div className="relative h-72">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series} margin={{ top: 16, right: 16, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="liveg" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--cyan)" stopOpacity={0.35} />
                <stop offset="100%" stopColor="var(--cyan)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="oklch(1 0 0 / 6%)" vertical={false} />
            <XAxis
              dataKey="t"
              tickFormatter={(v) => new Date(v).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              tick={{ fontSize: 10, fill: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}
              axisLine={false}
              tickLine={false}
              minTickGap={48}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fontSize: 10, fill: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => fmt(v)}
              width={56}
              orientation="right"
            />
            <Tooltip
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
                fontFamily: "var(--font-mono)",
              }}
              labelFormatter={(v) => new Date(v).toLocaleString()}
              formatter={(v: number) => [fmt(v), "Price"]}
            />
            <ReferenceLine
              y={active.target}
              stroke="var(--cyan)"
              strokeDasharray="4 4"
              label={{ value: `TARGET ${fmt(active.target)}`, position: "insideTopRight", fill: "var(--cyan)", fontSize: 10, fontFamily: "var(--font-mono)" }}
            />
            <ReferenceLine
              y={active.entry}
              stroke="var(--gold)"
              strokeDasharray="2 4"
              label={{ value: `ENTRY ${fmt(active.entry)}`, position: "insideTopRight", fill: "var(--gold)", fontSize: 10, fontFamily: "var(--font-mono)" }}
            />
            <ReferenceLine
              y={active.stop}
              stroke="var(--danger)"
              strokeDasharray="4 4"
              label={{ value: `STOP ${fmt(active.stop)}`, position: "insideBottomRight", fill: "var(--danger)", fontSize: 10, fontFamily: "var(--font-mono)" }}
            />
            <Area
              type="monotone"
              dataKey="price"
              stroke="var(--cyan)"
              strokeWidth={2}
              fill="url(#liveg)"
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Strategy switcher */}
      {candidates.length > 1 && (
        <div className="flex gap-1.5 overflow-x-auto border-t border-border bg-background/40 px-3 py-2">
          {candidates.map((c) => {
            const isActive = c.id === active.id;
            return (
              <button
                key={c.id}
                onClick={() => setActiveId(c.id)}
                className={cn(
                  "flex shrink-0 items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] transition-colors",
                  isActive
                    ? "border-cyan/40 bg-cyan/10 text-cyan"
                    : "border-border bg-elevated text-muted-foreground hover:text-foreground",
                )}
              >
                <span className="font-mono font-semibold">{c.symbol}</span>
                <span className="max-w-[160px] truncate">{c.strategyName}</span>
                <span className={cn("font-mono", c.direction === "LONG" ? "text-cyan" : "text-danger")}>
                  {c.direction}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function Kv({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className={cn("font-semibold", tone === "pos" ? "text-cyan" : tone === "neg" ? "text-danger" : "text-foreground")}>
        {value}
      </span>
    </div>
  );
}
