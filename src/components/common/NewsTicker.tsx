import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getMarketNews } from "@/lib/api";
import { Newspaper, Settings2 } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useNewsCategories, ALL_NEWS_CATEGORIES, type NewsCategory } from "@/lib/user-prefs";
import { cn } from "@/lib/utils";

export function NewsTicker() {
  const { data } = useQuery({ queryKey: ["news"], queryFn: getMarketNews });
  const [cats, setCats] = useNewsCategories();

  const news = useMemo(() => {
    const set = new Set(cats);
    return (data ?? []).filter((n) => set.has(n.category));
  }, [data, cats]);

  if (!data?.length) return null;
  const loop = news.length ? [...news, ...news] : [];

  return (
    <div className="marquee-pause relative overflow-hidden rounded-xl border border-border bg-elevated">
      <div className="flex items-stretch">
        <div className="flex shrink-0 items-center gap-1.5 border-r border-border bg-background/50 px-3 text-[10px] font-mono uppercase tracking-[0.18em] text-muted-foreground">
          <Newspaper className="size-3 text-gold" /> Market wire
        </div>
        <NewsCatMenu selected={cats} onChange={setCats} />
        <div className="relative flex-1 overflow-hidden">
          {!news.length ? (
            <div className="px-3 py-2.5 text-xs text-muted-foreground">
              No categories selected — click the gear to choose sectors.
            </div>
          ) : (
            <div className="marquee-track marquee-slow items-center gap-8 py-2.5 text-xs">
              {loop.map((n, i) => {
                const tone =
                  n.sentiment === "pos" ? "text-cyan"
                  : n.sentiment === "neg" ? "text-danger"
                  : "text-muted-foreground";
                return (
                  <div key={`${n.id}-${i}`} className="flex shrink-0 items-center gap-2">
                    <span className="rounded-sm bg-muted/40 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                      {n.source}
                    </span>
                    <span className="rounded-sm border border-border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                      {n.category}
                    </span>
                    {n.symbol && (
                      <span className={`font-mono text-[11px] font-semibold ${tone}`}>{n.symbol}</span>
                    )}
                    <span className="text-foreground">{n.headline}</span>
                    <span className="font-mono text-[10px] text-muted-foreground">· {n.minutesAgo}m ago</span>
                    <span className="text-border">|</span>
                  </div>
                );
              })}
            </div>
          )}
          <div className="pointer-events-none absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-elevated to-transparent" />
        </div>
      </div>
    </div>
  );
}

function NewsCatMenu({
  selected, onChange,
}: { selected: NewsCategory[]; onChange: (next: NewsCategory[]) => void }) {
  const set = new Set(selected);
  const toggle = (c: NewsCategory) => {
    const next = new Set(set);
    next.has(c) ? next.delete(c) : next.add(c);
    onChange([...next]);
  };
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          className="grid shrink-0 place-items-center border-r border-border bg-background/50 px-2 text-muted-foreground hover:text-foreground"
          aria-label="Customize news sectors"
          title="Customize news sectors"
        >
          <Settings2 className="size-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-60 p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-muted-foreground">
            News sectors
          </span>
          <button
            className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground"
            onClick={() => onChange([...ALL_NEWS_CATEGORIES])}
          >
            all
          </button>
        </div>
        <div className="space-y-0.5">
          {ALL_NEWS_CATEGORIES.map((c) => {
            const on = set.has(c);
            return (
              <button
                key={c}
                onClick={() => toggle(c)}
                className={cn(
                  "flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs transition-colors",
                  on ? "bg-gold/10 text-gold" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
              >
                <span>{c}</span>
                <span className="text-[10px] font-mono">{on ? "ON" : "OFF"}</span>
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
