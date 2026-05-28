import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { getSignals } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAssetFilter } from "@/lib/asset-filter";
import { SignalRow, SignalGroup } from "@/components/common/SignalRow";
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

  useEffect(() => { setStatus("all"); }, [assetClass]);

  const list = useMemo(() => {
    return (data ?? [])
      .filter((s) => assetClass === "all" || s.assetClass === assetClass)
      .filter((s) => status === "all" || s.status === status);
  }, [data, assetClass, status]);

  const open = list.filter((s) => s.status === "OPEN");
  const today = list.filter((s) => {
    if (s.status === "OPEN") return false;
    const diff = Date.now() - +new Date(s.firedAt);
    return diff < 24 * 60 * 60 * 1000;
  });
  const older = list.filter((s) => s.status !== "OPEN" && !today.includes(s));

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Signals {assetClass !== "all" && <span className="text-muted-foreground">· {assetClass}</span>}
        </h1>
        <p className="text-sm text-muted-foreground">
          Live signals from your followed strategies, grouped by state.
        </p>
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
          <div className="rounded-lg border border-dashed border-border bg-elevated/40 px-4 py-12 text-center text-sm text-muted-foreground">
            No signals match these filters.
          </div>
        )}
      </div>
    </div>
  );
}
