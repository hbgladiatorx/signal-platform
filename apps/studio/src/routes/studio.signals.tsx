import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getPersonalSignals } from "@/lib/api/studio";
import { Card } from "@/components/ui/card";
import { Inbox } from "lucide-react";
import { SignalRow, SignalGroup } from "@/components/common/SignalRow";

export const Route = createFileRoute("/studio/signals")({
  head: () => ({ meta: [{ title: "Live Signals — Bayn Studio" }] }),
  component: StudioSignals,
});

function StudioSignals() {
  const { data } = useQuery({ queryKey: ["personalSignals"], queryFn: () => getPersonalSignals() });
  const list = data ?? [];

  const groups = useMemo(() => {
    const open = list.filter((s) => s.status === "OPEN");
    const today = list.filter((s) => {
      if (s.status === "OPEN") return false;
      return Date.now() - +new Date(s.firedAt) < 24 * 60 * 60 * 1000;
    });
    const older = list.filter((s) => s.status !== "OPEN" && !today.includes(s));
    return { open, today, older };
  }, [list]);

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Live signals</h1>
        <p className="text-sm text-muted-foreground">
          Signals from your own strategies running on live data. Private to you.
        </p>
      </div>

      {!list.length ? (
        <Card className="border-dashed border-border bg-elevated/40 p-10 text-center text-sm text-muted-foreground">
          <Inbox className="mx-auto mb-2 size-8 opacity-50" />
          No signals yet. Deploy a strategy to start.
        </Card>
      ) : (
        <div className="space-y-6">
          {groups.open.length > 0 && (
            <SignalGroup title="Open · live" count={groups.open.length}>
              {groups.open.map((s) => (
                <SignalRow key={s.id} sig={s} ownStrategyName={s.ownStrategyName} mode="studio" />
              ))}
            </SignalGroup>
          )}
          {groups.today.length > 0 && (
            <SignalGroup title="Closed today" count={groups.today.length}>
              {groups.today.map((s) => (
                <SignalRow key={s.id} sig={s} ownStrategyName={s.ownStrategyName} mode="studio" />
              ))}
            </SignalGroup>
          )}
          {groups.older.length > 0 && (
            <SignalGroup title="Earlier" count={groups.older.length}>
              {groups.older.map((s) => (
                <SignalRow key={s.id} sig={s} ownStrategyName={s.ownStrategyName} mode="studio" />
              ))}
            </SignalGroup>
          )}
        </div>
      )}
    </div>
  );
}
