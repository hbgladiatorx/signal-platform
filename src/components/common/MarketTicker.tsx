import { useQuery } from "@tanstack/react-query";
import { getMarketOverview } from "@/lib/api";
import { TrendingUp, TrendingDown } from "lucide-react";

const fmt = (n: number) =>
  n >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 0 })
            : n.toLocaleString(undefined, { maximumFractionDigits: 2 });

/** Bloomberg-style horizontal scrolling price strip. */
export function MarketTicker() {
  const { data } = useQuery({ queryKey: ["market"], queryFn: getMarketOverview });
  const tiles = data ?? [];
  if (!tiles.length) return <div className="h-8 border-y border-border bg-elevated/40" />;
  const loop = [...tiles, ...tiles];

  return (
    <div className="marquee-pause relative overflow-hidden border-y border-border bg-elevated/60">
      <div className="marquee-track items-center gap-7 py-1.5 font-mono text-[11px] tracking-tight">
        {loop.map((t, i) => {
          const up = t.changePct >= 0;
          return (
            <div key={`${t.symbol}-${i}`} className="flex shrink-0 items-center gap-1.5">
              <span className="font-semibold text-foreground">{t.symbol}</span>
              <span className="text-muted-foreground">{fmt(t.price)}</span>
              <span className={up ? "text-cyan inline-flex items-center gap-0.5" : "text-danger inline-flex items-center gap-0.5"}>
                {up ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
                {up ? "+" : ""}{t.changePct.toFixed(2)}%
              </span>
              <span className="mx-2 text-border">·</span>
            </div>
          );
        })}
      </div>
      <div className="pointer-events-none absolute inset-y-0 left-0 w-12 bg-gradient-to-r from-background to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-background to-transparent" />
    </div>
  );
}
