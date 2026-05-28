import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  getStrategies, subscribeToStrategy, unsubscribeFromStrategy, getEffectiveFollowedIds,
} from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { PipelineBadge } from "@/components/common/PipelineBadge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Users, Check, Plus, Lock } from "lucide-react";
import { useAssetFilter } from "@/lib/asset-filter";
import { useFollowedOverlay, useEnabledAssetClasses } from "@/lib/user-prefs";
import { checkSlotAvailability, isFreeStrategy } from "@/lib/api/billing";
import { PaywallModal } from "@/components/billing/PaywallModal";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/app/catalog")({
  head: () => ({ meta: [{ title: "Strategy catalog — Bayn" }, { name: "description", content: "Browse verified trading strategies across stocks, crypto, options and futures." }] }),
  component: CatalogPage,
});


function CatalogPage() {
  const { assetClass } = useAssetFilter();
  const [enabledClasses] = useEnabledAssetClasses();
  const [sort, setSort] = useState("subs");
  const [q, setQ] = useState("");
  const [paywallId, setPaywallId] = useState<string | null>(null);
  const { data } = useQuery({ queryKey: ["strategies"], queryFn: getStrategies });
  const queryClient = useQueryClient();

  useFollowedOverlay();
  const followedNow = new Set(getEffectiveFollowedIds());
  const followedNonFree = [...followedNow].filter((id) => !isFreeStrategy(id));

  const subscribe = useMutation({
    mutationFn: subscribeToStrategy,
    onSuccess: (_d, id) => {
      queryClient.invalidateQueries({ queryKey: ["followed"] });
      const s = data?.find((x) => x.id === id);
      toast.success(`Following ${s?.name ?? "strategy"} — live signals will appear on Home`);
    },
  });
  const unsubscribe = useMutation({
    mutationFn: unsubscribeFromStrategy,
    onSuccess: (_d, id) => {
      queryClient.invalidateQueries({ queryKey: ["followed"] });
      const s = data?.find((x) => x.id === id);
      toast(`Unfollowed ${s?.name ?? "strategy"}`);
    },
  });

  const tryFollow = (id: string) => {
    const check = checkSlotAvailability(id, followedNonFree);
    if (check.ok) subscribe.mutate(id);
    else setPaywallId(id);
  };

  const list = useMemo(() => {
    let arr = data ?? [];
    // Master asset-class cascade.
    const enabled = new Set(enabledClasses);
    arr = arr.filter((s) => enabled.has(s.assetClass));
    if (assetClass !== "all") arr = arr.filter((s) => s.assetClass === assetClass);
    if (q) arr = arr.filter((s) => (s.name + " " + s.description).toLowerCase().includes(q.toLowerCase()));
    arr = [...arr].sort((a, b) => {
      if (sort === "subs") return b.stats.subscribers - a.stats.subscribers;
      if (sort === "sharpe") return b.stats.sharpe - a.stats.sharpe;
      if (sort === "dd") return a.stats.maxDrawdown - b.stats.maxDrawdown;
      return +new Date(b.createdAt) - +new Date(a.createdAt);
    });
    return arr;
  }, [data, assetClass, sort, q, enabledClasses]);


  return (
    <div className="space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Strategy catalog {assetClass !== "all" && <span className="text-muted-foreground">· {assetClass}</span>}
        </h1>
        <p className="text-sm text-muted-foreground">Every strategy here has cleared Bayn's 5-stage edge pipeline.</p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search strategies…" className="h-9 bg-elevated md:w-64" />
        <Select value={sort} onValueChange={setSort}>
          <SelectTrigger className="h-9 w-44 bg-elevated"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="subs">Most followed</SelectItem>
            <SelectItem value="sharpe">Highest Sharpe</SelectItem>
            <SelectItem value="new">Newest</SelectItem>
            <SelectItem value="dd">Lowest drawdown</SelectItem>
          </SelectContent>
        </Select>
        <div className="ml-auto text-xs text-muted-foreground">{list.length} strategies</div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {list.map((s) => {
          const isFollowed = followedNow.has(s.id);
          return (
            <Card key={s.id} className={cn(
              "group flex h-full flex-col gap-3 border-border bg-elevated p-5 transition-colors",
              isFollowed ? "border-cyan/40" : "hover:border-cyan/30",
            )}>
              <Link to="/app/strategy/$id" params={{ id: s.id }} className="flex flex-col gap-3">
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
              </Link>
              <div className="flex items-center justify-between pt-1">
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <Users className="size-3" /> {s.stats.subscribers.toLocaleString()} followers
                </span>
                {isFollowed ? (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 gap-1 border-cyan/40 bg-cyan/10 text-cyan hover:bg-cyan/15"
                    onClick={(e) => { e.preventDefault(); unsubscribe.mutate(s.id); }}
                  >
                    <Check className="size-3" /> Following
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 gap-1"
                    onClick={(e) => { e.preventDefault(); tryFollow(s.id); }}
                  >
                    {isFreeStrategy(s.id) ? <Plus className="size-3" /> : <Lock className="size-3" />}
                    {isFreeStrategy(s.id) ? "Follow" : "$99/mo"}
                  </Button>
                )}
              </div>
            </Card>
          );
        })}
        {list.length === 0 && (
          <Card className="col-span-full border-dashed border-border bg-elevated/50 p-10 text-center text-sm text-muted-foreground">
            No {assetClass !== "all" ? assetClass + " " : ""}strategies match your search.
          </Card>
        )}
      </div>
      <PaywallModal
        strategyId={paywallId}
        open={!!paywallId}
        onOpenChange={(open) => !open && setPaywallId(null)}
        onResolved={() => {
          queryClient.invalidateQueries({ queryKey: ["followed"] });
          setPaywallId(null);
        }}
      />
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
