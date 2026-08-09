import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { getQuotes } from "@/lib/api/finnhub.functions";
import { TrendingUp, TrendingDown, Settings2 } from "lucide-react";
import { useWatchlist } from "@/lib/user-prefs";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const fmt = (n: number) =>
  n >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 0 })
            : n.toLocaleString(undefined, { maximumFractionDigits: 2 });

/** Bloomberg-style horizontal scrolling price strip — live Finnhub quotes. */
export function MarketTicker() {
  const [watchlist, setWatchlist] = useWatchlist();
  const quotesFn = useServerFn(getQuotes);
  const { data } = useQuery({
    queryKey: ["quotes", watchlist],
    queryFn: () => quotesFn({ data: { symbols: watchlist } }),
    enabled: watchlist.length > 0,
    refetchInterval: 30_000,
    staleTime: 25_000,
  });

  const tiles = useMemo(() => {
    const order = new Map(watchlist.map((s, i) => [s.toUpperCase(), i] as const));
    return (data ?? [])
      .slice()
      .sort((a, b) => (order.get(a.symbol) ?? 0) - (order.get(b.symbol) ?? 0));
  }, [data, watchlist]);

  const loop = tiles.length ? [...tiles, ...tiles] : [];

  return (
    <div className="marquee-pause relative flex items-center border-y border-border bg-elevated/60">
      <WatchlistMenu selected={watchlist} onChange={setWatchlist} />
      <div className="relative flex-1 overflow-hidden">
        {!watchlist.length ? (
          <div className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
            No tickers selected — click the gear to add symbols.
          </div>
        ) : !tiles.length ? (
          <div className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
            Loading live quotes…
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
  selected, onChange,
}: { selected: string[]; onChange: (next: string[]) => void }) {
  const [custom, setCustom] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = new Set(selected);

  const validateAndAdd = async () => {
    const sym = custom.trim().toUpperCase();
    if (!sym) return;
    if (set.has(sym)) { setCustom(""); return; }
    setBusy(true);
    setStatus(null);
    try {
      const { validateTicker } = await import("@/lib/api/finnhub.functions");
      const fn = validateTicker;
      const res = await fn({ data: { symbol: sym } });
      if (res.valid) {
        onChange([...selected, res.symbol]);
        setCustom("");
        setStatus(null);
      } else {
        setStatus(`"${sym}" not found`);
      }
    } catch {
      setStatus("Validation failed");
    } finally {
      setBusy(false);
    }
  };

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
            onClick={() => onChange([])}
          >
            clear
          </button>
        </div>
        <div className="mb-1 flex gap-1.5">
          <Input
            value={custom}
            onChange={(e) => { setCustom(e.target.value); setStatus(null); }}
            onKeyDown={(e) => e.key === "Enter" && validateAndAdd()}
            placeholder="Add ticker…"
            className="h-7 bg-background font-mono text-xs"
            disabled={busy}
          />
          <Button size="sm" className="h-7 px-2 text-xs" onClick={validateAndAdd} disabled={busy}>
            {busy ? "…" : "Add"}
          </Button>
        </div>
        {status && <div className="mb-2 text-[10px] text-danger">{status}</div>}
        <div className="max-h-64 space-y-0.5 overflow-y-auto">
          {selected.length === 0 && (
            <div className="px-2 py-3 text-center text-[11px] text-muted-foreground">
              No symbols yet.
            </div>
          )}
          {selected.map((sym) => (
            <button
              key={sym}
              onClick={() => onChange(selected.filter((s) => s !== sym))}
              className={cn(
                "flex w-full items-center justify-between rounded px-2 py-1 text-left font-mono text-xs transition-colors",
                "bg-cyan/10 text-cyan hover:bg-danger/15 hover:text-danger",
              )}
            >
              <span>{sym}</span>
              <span className="text-[10px]">remove</span>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
