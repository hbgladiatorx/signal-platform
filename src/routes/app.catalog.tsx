import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { getStrategies } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { PipelineBadge } from "@/components/common/PipelineBadge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { AssetClass } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Users } from "lucide-react";

export const Route = createFileRoute("/app/catalog")({
  head: () => ({ meta: [{ title: "Strategy catalog — Bayn" }, { name: "description", content: "Browse verified trading strategies across stocks, crypto, options and futures." }] }),
  component: CatalogPage,
});

const filters: Array<{ key: "all" | AssetClass; label: string }> = [
  { key: "all", label: "All" },
  { key: "stocks", label: "Stocks" },
  { key: "crypto", label: "Crypto" },
  { key: "options", label: "Options" },
  { key: "futures", label: "Futures" },
];

function CatalogPage() {
  const [filter, setFilter] = useState<"all" | AssetClass>("all");
  const [sort, setSort] = useState("subs");
  const [q, setQ] = useState("");
  const { data } = useQuery({ queryKey: ["strategies"], queryFn: getStrategies });

  const list = useMemo(() => {
    let arr = data ?? [];
    if (filter !== "all") arr = arr.filter((s) => s.assetClass === filter);
    if (q) arr = arr.filter((s) => (s.name + " " + s.description).toLowerCase().includes(q.toLowerCase()));
    arr = [...arr].sort((a, b) => {
      if (sort === "subs") return b.stats.subscribers - a.stats.subscribers;
      if (sort === "sharpe") return b.stats.sharpe - a.stats.sharpe;
      if (sort === "dd") return a.stats.maxDrawdown - b.stats.maxDrawdown;
      return +new Date(b.createdAt) - +new Date(a.createdAt);
    });
    return arr;
  }, [data, filter, sort, q]);

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Strategy catalog</h1>
        <p className="text-sm text-muted-foreground">Every strategy here has cleared Bayn's 5-stage edge pipeline.</p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {filters.map((f) => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              filter === f.key ? "border-cyan/40 bg-cyan/15 text-cyan" : "border-border bg-elevated text-muted-foreground hover:text-foreground",
            )}>
            {f.label}
          </button>
        ))}
        <div className="ml-auto flex w-full items-center gap-2 md:w-auto">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" className="h-9 bg-elevated md:w-64" />
          <Select value={sort} onValueChange={setSort}>
            <SelectTrigger className="h-9 w-44 bg-elevated"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="subs">Most followed</SelectItem>
              <SelectItem value="sharpe">Highest Sharpe</SelectItem>
              <SelectItem value="new">Newest</SelectItem>
              <SelectItem value="dd">Lowest drawdown</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {list.map((s) => (
          <Link key={s.id} to="/strategy/$id" params={{ id: s.id }}>
            <Card className="group flex h-full flex-col gap-3 border-border bg-elevated p-5 transition-colors hover:border-cyan/30">
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-semibold leading-tight group-hover:text-cyan">{s.name}</h3>
                <AssetClassBadge assetClass={s.assetClass} hideIcon />
              </div>
              <p className="text-sm text-muted-foreground line-clamp-2">{s.description}</p>
              <div><PipelineBadge compact /></div>
              <div className="mt-auto grid grid-cols-4 gap-2 border-t border-border pt-3 text-center">
                <Stat label="Sharpe" value={s.stats.sharpe.toFixed(2)} />
                <Stat label="Win" value={`${(s.stats.winRate * 100).toFixed(0)}%`} />
                <Stat label="Max DD" value={`${(s.stats.maxDrawdown * 100).toFixed(0)}%`} />
                <Stat label="Live" value={`${s.stats.liveDays}d`} />
              </div>
              <div className="flex items-center justify-between pt-1">
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <Users className="size-3" /> {s.stats.subscribers.toLocaleString()} followers
                </span>
                <Button size="sm" variant="outline" className="h-7">Subscribe</Button>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-sm">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}
