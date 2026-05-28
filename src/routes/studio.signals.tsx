import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { getPersonalSignals } from "@/lib/api/studio";
import { Card } from "@/components/ui/card";
import { DirectionPill } from "@/components/common/DirectionPill";
import { StatusPill } from "@/components/common/StatusPill";
import { Sparkline } from "@/components/common/Sparkline";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { formatDistanceToNow } from "date-fns";
import { Inbox } from "lucide-react";

export const Route = createFileRoute("/studio/signals")({
  head: () => ({ meta: [{ title: "Live Signals — Bayn Studio" }] }),
  component: StudioSignals,
});

function StudioSignals() {
  const { data } = useQuery({ queryKey: ["personalSignals"], queryFn: () => getPersonalSignals() });
  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Live signals</h1>
        <p className="text-sm text-muted-foreground">Signals from your own strategies running on live data. Private to you.</p>
      </div>
      <Card className="border-border bg-elevated">
        {!data?.length ? (
          <div className="p-10 text-center text-sm text-muted-foreground">
            <Inbox className="mx-auto mb-2 size-8 opacity-50" />
            No signals yet. Deploy a strategy to start.
          </div>
        ) : (
          <div className="divide-y divide-border">
            {data.map((sig) => (
              <Link key={sig.id} to="/app/signal/$id" params={{ id: sig.id }} className="grid grid-cols-12 items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/30">
                <div className="col-span-2 text-xs text-muted-foreground">{formatDistanceToNow(new Date(sig.firedAt), { addSuffix: true })}</div>
                <div className="col-span-3 truncate">
                  <div className="truncate text-sm font-medium">{sig.ownStrategyName}</div>
                  <div className="flex items-center gap-1.5"><span className="font-mono text-xs text-violet">{sig.symbol}</span> <AssetClassBadge assetClass={sig.assetClass} hideIcon /></div>
                </div>
                <div className="col-span-1"><DirectionPill direction={sig.direction} /></div>
                <div className="col-span-3 font-mono text-xs text-muted-foreground">
                  <span className="text-foreground">{sig.entry}</span> · stop {sig.stop} · tgt {sig.target}
                </div>
                <div className="col-span-1"><StatusPill status={sig.status} /></div>
                <div className="col-span-2 h-8"><Sparkline data={sig.priceSeries.slice(-30).map((p) => p.price)} positive={sig.direction === "LONG"} /></div>
              </Link>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
