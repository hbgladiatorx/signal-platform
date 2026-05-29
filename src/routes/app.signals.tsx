import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { getSignals, useFollowedIds } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAssetFilter } from "@/lib/asset-filter";
import { SignalRow, SignalGroup } from "@/components/common/SignalRow";

import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Inbox } from "lucide-react";
import type { SignalStatus } from "@/lib/types";

export const Route = createFileRoute("/app/signals")({
  head: () => ({ meta: [{ title: "Signals — Bayn" }] }),
  component: SignalsPage,
});

const statusFilters: Array<{ key: "all" | SignalStatus; label: string }> = [
  { key: "all", label: "All" },
  { key: "OPEN", label: "Open" },
  { key: "HIT_TARGET", label: "Won" },
  { key: "HIT_STOP", label: "Lost" },
  { key: "EXPIRED", label: "Expired" },
];

function SignalsPage() {
  const { assetClass } = useAssetFilter();
  const [status, setStatus] = useState<"all" | SignalStatus>("all");
  const { data } = useQuery({ queryKey: ["signals-all"], queryFn: () => getSignals() });
  const { data } = useQuery({ queryKey: ["signals-all"], queryFn: () => getSignals() });
  const followedList = useFollowedIds();
  const followedIds = useMemo(() => new Set<string>(followedList), [followedList]);


  useEffect(() => { setStatus("all"); }, [assetClass]);

  const list = useMemo(() => {
    return (data ?? [])
      .filter((s) => followedIds.has(s.strategyId))
      .filter((s) => assetClass === "all" || s.assetClass === assetClass)
      .filter((s) => status === "all" || s.status === status);
  }, [data, assetClass, status, followedIds]);


  const open = list.filter((s) => s.status === "OPEN");
  const today = list.filter((s) => {
    if (s.status === "OPEN") return false;
    const diff = Date.now() - +new Date(s.firedAt);
    return diff < 24 * 60 * 60 * 1000;
  });
  const older = list.filter((s) => s.status !== "OPEN" && !today.includes(s));

  const openCount = list.filter((s) => s.status === "OPEN").length;
  const wonCount  = list.filter((s) => s.status === "HIT_TARGET").length;
  const lostCount = list.filter((s) => s.status === "HIT_STOP").length;
  const closed = list.filter((s) => s.status === "HIT_TARGET" || s.status === "HIT_STOP").length;
  const winRate = closed ? wonCount / closed : 0;

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Signals {assetClass !== "all" && <span className="text-muted-foreground">· {assetClass}</span>}
          </h1>
          <p className="text-sm text-muted-foreground">
            Live signals from your followed strategies, grouped by state.
          </p>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Kpi label="Open" value={openCount} tone="cyan" />
        <Kpi label="Won" value={wonCount} tone="cyan" />
        <Kpi label="Lost" value={lostCount} tone="danger" />
        <Kpi label="Win rate" value={closed ? `${(winRate * 100).toFixed(0)}%` : "—"} />
      </div>

      <div className="flex flex-wrap gap-2">
        {statusFilters.map((f) => (
          <button
            key={f.key}
            onClick={() => setStatus(f.key)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              status === f.key
                ? "border-cyan/40 bg-cyan/15 text-cyan"
                : "border-border bg-elevated text-muted-foreground hover:text-foreground",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="space-y-6">
        {(status === "all" || status === "OPEN") && open.length > 0 && (
          <SignalGroup title="Open · live" count={open.length}>
            {open.map((s) => <SignalRow key={s.id} sig={s} />)}
          </SignalGroup>
        )}

        {status === "all" && today.length > 0 && (
          <SignalGroup title="Closed today" count={today.length}>
            {today.map((s) => <SignalRow key={s.id} sig={s} />)}
          </SignalGroup>
        )}

        {(status === "all" ? older : list.filter((s) => s.status === status && (status !== "OPEN"))).length > 0 && (
          <SignalGroup
            title={status === "all" ? "Earlier" : status === "OPEN" ? "" : "Results"}
            count={(status === "all" ? older : list.filter((s) => s.status === status && status !== "OPEN")).length}
          >
            {(status === "all" ? older : list.filter((s) => s.status === status && status !== "OPEN")).map((s) => (
              <SignalRow key={s.id} sig={s} />
            ))}
          </SignalGroup>
        )}

        {list.length === 0 && (
          <Card className="grid place-items-center gap-3 border-dashed border-border bg-elevated/40 p-10 text-center text-sm text-muted-foreground">
            <Inbox className="size-8 opacity-50" />
            <div>
              {followedIds.size === 0
                ? "You're not following any strategies yet — signals appear here once you subscribe."
                : "No signals from your followed strategies match these filters."}
            </div>
            <Button asChild size="sm"><Link to="/app/catalog">Browse catalog</Link></Button>
          </Card>
        )}

      </div>
    </div>
  );
}

function Kpi({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "cyan" | "danger" }) {
  return (
    <div className="rounded-lg border border-border bg-elevated p-3">
      <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">{label}</div>
      <div className={cn(
        "mt-1 font-mono text-2xl",
        tone === "cyan" && "text-cyan",
        tone === "danger" && "text-danger",
      )}>
        {value}
      </div>
    </div>
  );
}

