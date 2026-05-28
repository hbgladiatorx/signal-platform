import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { getSignals } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { DirectionPill } from "@/components/common/DirectionPill";
import { StatusPill } from "@/components/common/StatusPill";
import { Sparkline } from "@/components/common/Sparkline";
import { formatDistanceToNow } from "date-fns";
import { cn } from "@/lib/utils";
import { useAssetFilter } from "@/lib/asset-filter";
import type { SignalStatus } from "@/lib/types";

export const Route = createFileRoute("/app/signals")({
  head: () => ({ meta: [{ title: "Signals — Bayn" }] }),
  component: SignalsPage,
});

const statusFilters: Array<{ key: "all" | SignalStatus; label: string }> = [
  { key: "all", label: "All status" },
  { key: "OPEN", label: "Open" },
  { key: "HIT_TARGET", label: "Won" },
  { key: "HIT_STOP", label: "Lost" },
  { key: "EXPIRED", label: "Expired" },
];

function SignalsPage() {
  const { assetClass } = useAssetFilter();
  const [status, setStatus] = useState<"all" | SignalStatus>("all");
  const { data } = useQuery({ queryKey: ["signals-all"], queryFn: () => getSignals() });

  // Reset status filter if asset class change makes it irrelevant
  useEffect(() => { setStatus("all"); }, [assetClass]);

  const list = useMemo(() => {
    return (data ?? [])
      .filter((s) => assetClass === "all" || s.assetClass === assetClass)
      .filter((s) => status === "all" || s.status === status);
  }, [data, assetClass, status]);

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Signals {assetClass !== "all" && <span className="text-muted-foreground">· {assetClass}</span>}
        </h1>
        <p className="text-sm text-muted-foreground">
          Every signal from your followed strategies. Asset filter above scopes the feed.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {statusFilters.map((f) => (
          <button key={f.key} onClick={() => setStatus(f.key)}
            className={cn("rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              status === f.key ? "border-cyan/40 bg-cyan/15 text-cyan" : "border-border bg-elevated text-muted-foreground hover:text-foreground")}>
            {f.label}
          </button>
        ))}
      </div>
      <Card className="border-border bg-elevated">
        <div className="divide-y divide-border">
          {list.map((sig) => (
            <Link key={sig.id} to="/app/signal/$id" params={{ id: sig.id }} className="grid grid-cols-12 items-center gap-3 px-4 py-3 hover:bg-muted/30">
              <div className="col-span-2 text-xs text-muted-foreground">{formatDistanceToNow(new Date(sig.firedAt), { addSuffix: true })}</div>
              <div className="col-span-3 truncate">
                <div className="truncate text-sm font-medium">{sig.strategyName}</div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground"><AssetClassBadge assetClass={sig.assetClass} hideIcon /> <span className="font-mono">{sig.symbol}</span></div>
              </div>
              <div className="col-span-1"><DirectionPill direction={sig.direction} /></div>
              <div className="col-span-3 font-mono text-xs text-muted-foreground">
                <span className="text-foreground">{sig.entry}</span> · stop {sig.stop} · tgt {sig.target}
              </div>
              <div className="col-span-1"><StatusPill status={sig.status} /></div>
              <div className="col-span-2 h-8"><Sparkline data={sig.priceSeries.slice(-30).map((p) => p.price)} positive={sig.direction === "LONG"} /></div>
            </Link>
          ))}
          {list.length === 0 && (
            <div className="px-4 py-10 text-center text-sm text-muted-foreground">
              No signals match these filters.
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
