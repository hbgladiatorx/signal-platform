import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useFollowedIds, getSignals } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Activity, ArrowUpRight } from "lucide-react";
import { useAssetFilter } from "@/lib/asset-filter";
import { useWatchlist } from "@/lib/user-prefs";
import { DirectionPill } from "./DirectionPill";
import { TradingViewChart } from "./TradingViewChart";
import { DraggableLevelsOverlay, type Levels } from "./DraggableLevelsOverlay";
import { cn } from "@/lib/utils";
import type { AssetClass } from "@/lib/types";


const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });

const TIMEFRAMES: Array<{ key: string; label: string }> = [
  { key: "1", label: "1m" },
  { key: "5", label: "5m" },
  { key: "15", label: "15m" },
  { key: "60", label: "1h" },
  { key: "D", label: "1D" },
  { key: "W", label: "1W" },
];

/** Hero chart that tracks the live signal(s) from the user's followed strategies.

 *  Falls back to the first watchlist ticker when no live signal is active. */
export function LiveTrackerChart() {
  const { assetClass } = useAssetFilter();
  const [watchlist] = useWatchlist();
  const followedIdList = useFollowedIds();
  const signals  = useQuery({ queryKey: ["recent"], queryFn: () => getSignals({ limit: 30 }) });

  const candidates = useMemo(() => {
    const followedIds = new Set(followedIdList);
    return (signals.data ?? [])
      .filter((s) => followedIds.has(s.strategyId))
      .filter((s) => assetClass === "all" || s.assetClass === assetClass)
      .slice(0, 4);
  }, [followedIdList, signals.data, assetClass]);

  const [activeId, setActiveId] = useState<string | null>(null);
  // Reset active selection whenever the asset filter changes so symbol updates instantly.
  useEffect(() => { setActiveId(null); }, [assetClass]);

  const active = candidates.find((c) => c.id === activeId) ?? candidates[0];
  const [interval, setIntervalKey] = useState<string>("60");

  // Default-ticker fallback: when no live signal is being tracked, show the
  // first ticker from the user's watchlist so the chart is never blank.
  if (!active) {
    const defaultSymbol = watchlist[0];
    if (!defaultSymbol) {
      return (
        <Card className="grid min-h-[320px] place-items-center border-dashed border-border bg-elevated/50 p-8 text-center">
          <div className="max-w-sm space-y-3">
            <Activity className="mx-auto size-9 text-muted-foreground" />
            <div>
              <h3 className="font-semibold">No ticker selected</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Add a ticker in Customize and it will populate this chart instantly.
              </p>
            </div>
          </div>
        </Card>
      );
    }
    const guessClass: AssetClass = defaultSymbol.includes(":") ? "crypto" : "stocks";
    return (
      <Card className="overflow-hidden border-border bg-elevated">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background/40 px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="grid size-9 place-items-center rounded-md border border-cyan/30 bg-cyan/10">
              <Activity className="size-4 text-cyan" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="pulse-dot text-[10px] font-mono uppercase tracking-[0.18em] text-cyan">Live</span>
                <span className="rounded-sm bg-muted/40 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  Default ticker
                </span>
              </div>
              <div className="truncate text-sm font-semibold leading-tight">{defaultSymbol}</div>
            </div>
          </div>
          <Button asChild variant="ghost" size="sm" className="h-7 gap-1 text-cyan">
            <Link to="/app/catalog">Find strategies <ArrowUpRight className="size-3.5" /></Link>
          </Button>
        </div>
        <div className="flex items-center justify-between gap-2 border-b border-border bg-background/20 px-3 py-2">
          <TimeframeBar value={interval} onChange={setIntervalKey} />
        </div>
        <div className="relative">
          <TradingViewChart
            key={`${defaultSymbol}-${interval}`}
            symbol={defaultSymbol}
            assetClass={guessClass}
            interval={interval}
            height={420}
          />
        </div>
      </Card>
    );
  }



  const series = active.priceSeries ?? [];
  const last = series[series.length - 1]?.price ?? active.entry;
  const isLong = active.direction === "LONG";
  const inWinDir = isLong ? last >= active.entry : last <= active.entry;
  const distToTarget = Math.abs((active.target - last) / last) * 100;
  const distToStop = Math.abs((active.stop - last) / last) * 100;

  const initialLevels: Levels = { entry: active.entry, stop: active.stop, target: active.target };

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

        <div className="flex flex-wrap items-center gap-3 font-mono text-xs">
          <Kv label="Symbol" value={active.symbol} />
          <DirectionPill direction={active.direction} />
          <Kv label="Last" value={fmt(last)} tone={inWinDir ? "pos" : "neg"} />
          <Kv label="To target" value={`${distToTarget.toFixed(2)}%`} tone="pos" />
          <Kv label="To stop" value={`${distToStop.toFixed(2)}%`} tone="neg" />
        </div>
      </div>

      {/* Toolbar: timeframe + open-signal */}
      <div className="flex items-center justify-between gap-2 border-b border-border bg-background/20 px-3 py-2">
        <TimeframeBar value={interval} onChange={setIntervalKey} />
        <Button asChild variant="ghost" size="sm" className="h-7 gap-1 text-cyan">
          <Link to="/app/signal/$id" params={{ id: active.id }}>
            Open signal <ArrowUpRight className="size-3.5" />
          </Link>
        </Button>
      </div>

      {/* TradingView chart with drag-to-adjust strategy plan overlay */}
      <div className="relative">
        <TradingViewChart
          // re-key so chart fully reinitialises when symbol/interval changes
          key={`${active.symbol}-${interval}`}
          symbol={active.symbol}
          assetClass={active.assetClass}
          interval={interval}
          height={420}
        />
        <DraggableLevelsOverlay initial={initialLevels} direction={active.direction} />
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

function TimeframeBar({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex items-center gap-0.5 rounded-md border border-border bg-background/60 p-0.5">
      {TIMEFRAMES.map((tf) => (
        <button
          key={tf.key}
          onClick={() => onChange(tf.key)}
          className={cn(
            "rounded px-2 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors",
            value === tf.key
              ? "bg-cyan/15 text-cyan"
              : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
          )}
        >
          {tf.label}
        </button>
      ))}
    </div>
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
