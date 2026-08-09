import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { getMarketNews } from "@/lib/api/finnhub.functions";
import { Newspaper, ExternalLink } from "lucide-react";
import { useEnabledAssetClasses, useWatchlist, useOnlyNewsForWatched } from "@/lib/user-prefs";

export function NewsTicker() {
  const newsFn = useServerFn(getMarketNews);
  const [enabledClasses] = useEnabledAssetClasses();
  const [watchlist] = useWatchlist();
  const [onlyWatched] = useOnlyNewsForWatched();

  const category = enabledClasses.includes("crypto") && enabledClasses.length === 1
    ? "crypto" as const
    : "general" as const;

  const { data } = useQuery({
    queryKey: ["finnhub-news", category],
    queryFn: () => newsFn({ data: { category } }),
    refetchInterval: 120_000,
    staleTime: 100_000,
  });

  const news = useMemo(() => {
    const items = data ?? [];
    if (!onlyWatched || !watchlist.length) return items.slice(0, 20);
    const watch = new Set(watchlist.map((s) => s.toUpperCase()));
    return items
      .filter((n) => (n.symbol ? watch.has(n.symbol.toUpperCase()) : false))
      .slice(0, 20);
  }, [data, watchlist, onlyWatched]);

  if (!news.length) return null;
  const loop = [...news, ...news];

  return (
    <div className="marquee-pause relative overflow-hidden rounded-xl border border-border bg-elevated">
      <div className="flex items-stretch">
        <div className="flex shrink-0 items-center gap-1.5 border-r border-border bg-background/50 px-3 text-[10px] font-mono uppercase tracking-[0.18em] text-muted-foreground">
          <Newspaper className="size-3 text-gold" /> Market wire
        </div>
        <div className="relative flex-1 overflow-hidden">
          <div className="marquee-track marquee-slow items-center gap-8 py-2.5 text-xs">
            {loop.map((n, i) => {
              const minsAgo = Math.max(0, Math.floor((Date.now() / 1000 - n.datetime) / 60));
              return (
                <a
                  key={`${n.id}-${i}`}
                  href={n.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex shrink-0 items-center gap-2 hover:text-foreground"
                >
                  <span className="rounded-sm bg-muted/40 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {n.source}
                  </span>
                  {n.symbol && (
                    <span className="font-mono text-[11px] font-semibold text-cyan">{n.symbol}</span>
                  )}
                  <span className="text-foreground">{n.headline}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">· {minsAgo}m ago</span>
                  <ExternalLink className="size-3 text-muted-foreground" />
                  <span className="text-border">|</span>
                </a>
              );
            })}
          </div>
          <div className="pointer-events-none absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-elevated to-transparent" />
        </div>
      </div>
    </div>
  );
}
