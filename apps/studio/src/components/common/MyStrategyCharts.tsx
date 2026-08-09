import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { getFollowedStrategies, getSignals } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Activity } from "lucide-react";
import { useAssetFilter } from "@/lib/asset-filter";
import { TradingViewChart } from "./TradingViewChart";
import { DraggableLevelsOverlay, type Levels } from "./DraggableLevelsOverlay";
import { DirectionPill } from "./DirectionPill";
import { AssetClassBadge } from "./AssetClassBadge";
import { cn } from "@/lib/utils";
import type { Signal, Strategy } from "@/lib/types";

const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 4 });

// Too many TradingView iframes hurt the page; cap the split grid and tell the
// user when more are hidden.
const MAX_PANELS = 6;

/**
 * "My strategies" split view: one chart panel per followed strategy, showing the
 * asset it last signalled on (TradingView) with that signal's entry/stop/target
 * drawn on the chart. Strategies that haven't fired yet show a waiting state.
 */
export function MyStrategyCharts() {
  const { assetClass } = useAssetFilter();
  const followed = useQuery({ queryKey: ["followed"], queryFn: getFollowedStrategies });
  // RLS scopes signals to the products the user follows, so this only returns
  // signals for strategies in "My strategies".
  const signals = useQuery({
    queryKey: ["my-strategy-signals"],
    queryFn: () => getSignals({ limit: 200 }),
  });

  const panels = useMemo(() => {
    const strats = (followed.data ?? []).filter(
      (s) => assetClass === "all" || s.assetClass === assetClass,
    );
    // latest signal per strategy (getSignals returns newest-first).
    const latest = new Map<string, Signal>();
    for (const sig of signals.data ?? []) {
      if (!latest.has(sig.strategyId)) latest.set(sig.strategyId, sig);
    }
    return strats.map((s) => ({ strategy: s, signal: latest.get(s.id) }));
  }, [followed.data, signals.data, assetClass]);

  if (followed.isLoading || signals.isLoading) {
    return (
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="h-[360px] animate-pulse rounded-lg bg-muted/20" />
        ))}
      </div>
    );
  }

  const shown = panels.slice(0, MAX_PANELS);
  const hidden = panels.length - shown.length;

  return (
    <>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {shown.map(({ strategy, signal }) => (
          <StrategyChartPanel key={strategy.id} strategy={strategy} signal={signal} />
        ))}
      </div>
      {hidden > 0 && (
        <p className="mt-2 text-center text-xs text-muted-foreground">
          +{hidden} more followed {hidden === 1 ? "strategy" : "strategies"} — open one to see its chart.
        </p>
      )}
    </>
  );
}

function StrategyChartPanel({ strategy, signal }: { strategy: Strategy; signal?: Signal }) {
  return (
    <Card className="overflow-hidden border-border bg-elevated">
      {/* Header: strategy + (if any) latest signal plan */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-background/40 px-3 py-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="grid size-7 shrink-0 place-items-center rounded-md border border-cyan/30 bg-cyan/10">
            <Activity className="size-3.5 text-cyan" />
          </div>
          <Link
            to="/app/strategy/$id"
            params={{ id: strategy.id }}
            className="truncate text-sm font-semibold leading-tight hover:text-cyan"
          >
            {strategy.name}
          </Link>
          <AssetClassBadge assetClass={strategy.assetClass} hideIcon />
        </div>
        {signal && (
          <div className="flex items-center gap-2 font-mono text-[11px]">
            <span className="rounded-sm bg-muted/40 px-1.5 py-0.5 uppercase tracking-wider text-muted-foreground">
              {signal.symbol}
            </span>
            <DirectionPill direction={signal.direction} />
          </div>
        )}
      </div>

      {signal ? (
        <>
          <div className="flex items-center gap-3 border-b border-border bg-background/20 px-3 py-1.5 font-mono text-[11px]">
            <Kv label="Entry" value={fmt(signal.entry)} />
            <Kv label="Stop" value={fmt(signal.stop)} tone="neg" />
            <Kv label="Target" value={fmt(signal.target)} tone="pos" />
          </div>
          <div className="relative">
            <TradingViewChart
              key={`${signal.symbol}-${signal.id}`}
              symbol={signal.symbol}
              assetClass={signal.assetClass}
              interval="60"
              height={300}
            />
            <DraggableLevelsOverlay
              initial={{ entry: signal.entry, stop: signal.stop, target: signal.target } as Levels}
              direction={signal.direction}
            />
          </div>
        </>
      ) : (
        <div className="grid min-h-[260px] place-items-center px-6 py-10 text-center">
          <div className="max-w-xs space-y-2">
            <Activity className="mx-auto size-7 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              No signals yet. When <span className="text-foreground">{strategy.name}</span> fires,
              its chart and entry/stop/target will appear here.
            </p>
          </div>
        </div>
      )}
    </Card>
  );
}

function Kv({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className={cn(tone === "pos" && "text-cyan", tone === "neg" && "text-danger")}>{value}</span>
    </div>
  );
}
