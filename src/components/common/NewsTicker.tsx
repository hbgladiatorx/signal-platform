import { useQuery } from "@tanstack/react-query";
import { getMarketNews } from "@/lib/api";
import { Newspaper } from "lucide-react";

export function NewsTicker() {
  const { data } = useQuery({ queryKey: ["news"], queryFn: getMarketNews });
  const news = data ?? [];
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
              const tone =
                n.sentiment === "pos" ? "text-cyan"
                : n.sentiment === "neg" ? "text-danger"
                : "text-muted-foreground";
              return (
                <div key={`${n.id}-${i}`} className="flex shrink-0 items-center gap-2">
                  <span className="rounded-sm bg-muted/40 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {n.source}
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
          <div className="pointer-events-none absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-elevated to-transparent" />
        </div>
      </div>
    </div>
  );
}
