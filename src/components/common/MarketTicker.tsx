import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getMarketOverview } from "@/lib/api";
import { TrendingUp, TrendingDown, Settings2 } from "lucide-react";
import { useWatchlist, DEFAULT_WATCHLIST } from "@/lib/user-prefs";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const fmt = (n: number) =>
  n >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 0 })
            : n.toLocaleString(undefined, { maximumFractionDigits: 2 });

/** Bloomberg-style horizontal scrolling price strip with customization. */
export function MarketTicker() {
  const { data } = useQuery({ queryKey: ["market"], queryFn: getMarketOverview });
  const [watchlist, setWatchlist] = useWatchlist();
  const all = data ?? [];
  const tiles = useMemo(() => {
    const order = new Map(watchlist.map((s, i) => [s, i] as const));
    return all
      .filter((t) => order.has(t.symbol))
      .sort((a, b) => (order.get(a.symbol) ?? 0) - (order.get(b.symbol) ?? 0));
  }, [all, watchlist]);

  const loop = tiles.length ? [...tiles, ...tiles] : [];

  return (
    <div className="marquee-pause relative flex items-center border-y border-border bg-elevated/60">
      <WatchlistMenu
        all={all.map((t) => t.symbol)}
        selected={watchlist}
        onChange={setWatchlist}
      />
      <div className="relative flex-1 overflow-hidden">
        {!tiles.length ? (
          <div className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
            No tickers selected — click the gear to add symbols.
          </div>
        ) : (
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
        )}
        <div className="pointer-events-none absolute inset-y-0 left-0 w-12 bg-gradient-to-r from-elevated to-transparent" />
        <div className="pointer-events-none absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-elevated to-transparent" />
      </div>
    </div>
  );
}

function WatchlistMenu({
  all, selected, onChange,
}: { all: string[]; selected: string[]; onChange: (next: string[]) => void }) {
  const [custom, setCustom] = useState("");
  const set = new Set(selected);
  const toggle = (sym: string) => {
    const next = new Set(set);
    next.has(sym) ? next.delete(sym) : next.add(sym);
    onChange([...next]);
  };
  const addCustom = () => {
    const sym = custom.trim().toUpperCase();
    if (!sym) return;
    if (set.has(sym)) return setCustom("");
    onChange([...selected, sym]);
    setCustom("");
  };
  const universe = Array.from(new Set([...all, ...selected])).sort();
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          className="grid h-full shrink-0 place-items-center border-r border-border bg-background/50 px-2 text-muted-foreground hover:text-foreground"
          aria-label="Customize watchlist"
          title="Customize watchlist"
        >
          <Settings2 className="size-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-muted-foreground">
            Watchlist
          </span>
          <button
            className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground"
            onClick={() => onChange(DEFAULT_WATCHLIST)}
          >
            reset
          </button>
        </div>
        <div className="mb-3 flex gap-1.5">
          <Input
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addCustom()}
            placeholder="Add ticker…"
            className="h-7 bg-background font-mono text-xs"
          />
          <Button size="sm" className="h-7 px-2 text-xs" onClick={addCustom}>Add</Button>
        </div>
        <div className="max-h-64 space-y-0.5 overflow-y-auto">
          {universe.map((sym) => {
            const on = set.has(sym);
            return (
              <button
                key={sym}
                onClick={() => toggle(sym)}
                className={cn(
                  "flex w-full items-center justify-between rounded px-2 py-1 text-left font-mono text-xs transition-colors",
                  on ? "bg-cyan/10 text-cyan" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
              >
                <span>{sym}</span>
                <span className="text-[10px]">{on ? "ON" : "OFF"}</span>
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
