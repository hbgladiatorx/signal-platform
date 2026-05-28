import { Link } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import { DirectionPill } from "./DirectionPill";
import { StatusPill } from "./StatusPill";
import { Sparkline } from "./Sparkline";
import { cn } from "@/lib/utils";
import type { Signal } from "@/lib/types";

/** A compact, terminal-style signal row. Mode controls the symbol/strategy color accent. */
export function SignalRow({
  sig,
  ownStrategyName,
  mode = "trader",
}: {
  sig: Signal;
  ownStrategyName?: string;
  mode?: "trader" | "studio";
}) {
  const accent = mode === "studio" ? "text-violet" : "text-foreground";
  return (
    <Link
      to="/app/signal/$id"
      params={{ id: sig.id }}
      className="grid grid-cols-12 items-center gap-3 px-4 py-2.5 transition-colors hover:bg-muted/30"
    >
      <div className="col-span-2 font-mono text-[11px] text-muted-foreground">
        {formatDistanceToNow(new Date(sig.firedAt), { addSuffix: true })}
      </div>
      <div className="col-span-3 min-w-0">
        <div className="flex items-center gap-2">
          <span className={cn("font-mono text-sm font-semibold", accent)}>{sig.symbol}</span>
          <span className="rounded-sm bg-muted/40 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            {sig.assetClass}
          </span>
        </div>
        <div className="truncate text-[11px] text-muted-foreground">
          {ownStrategyName ?? sig.strategyName}
        </div>
      </div>
      <div className="col-span-1"><DirectionPill direction={sig.direction} /></div>
      <div className="col-span-3 font-mono text-[11px] text-muted-foreground">
        <span className="text-foreground">{sig.entry}</span>
        <span className="mx-1 text-border">·</span> stop {sig.stop}
        <span className="mx-1 text-border">·</span> tgt {sig.target}
      </div>
      <div className="col-span-1"><StatusPill status={sig.status} /></div>
      <div className="col-span-2 h-7">
        <Sparkline
          data={sig.priceSeries.slice(-30).map((p) => p.price)}
          positive={sig.direction === "LONG"}
        />
      </div>
    </Link>
  );
}

export function SignalGroup({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 px-1 pb-2">
        <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-muted-foreground">
          {title}
        </span>
        <span className="rounded-sm bg-muted/40 px-1.5 font-mono text-[10px] text-muted-foreground">
          {count}
        </span>
        <div className="ml-2 h-px flex-1 bg-border/60" />
      </div>
      <div className="overflow-hidden rounded-lg border border-border bg-elevated">
        <div className="divide-y divide-border">{children}</div>
      </div>
    </div>
  );
}
