import { useEffect, useState } from "react";
import { Bug, ChevronDown, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getCurrentPlan } from "@/lib/api/billing";
import { getDebugEvents, clearDebugEvents, type DebugEvent } from "@/lib/debug-log";
import { getOnboarded, getStudioSeeded, getTraderSeeded } from "@/lib/user-prefs";
import { cn } from "@/lib/utils";

export function DebugPanel() {
  const [events, setEvents] = useState<DebugEvent[]>(() => getDebugEvents());
  const [open, setOpen] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const sync = () => {
      setEvents(getDebugEvents());
      setTick((n) => n + 1);
    };
    window.addEventListener("bayn-debug-event", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("bayn-debug-event", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const plan = getCurrentPlan();
  const summary = {
    onboarded: getOnboarded(),
    traderSeeded: getTraderSeeded(),
    studioSeeded: getStudioSeeded(),
    traderPlan: plan.trader ?? "free",
    studioPlan: plan.developer ?? "none",
  };
  const latest = events[0];

  return (
    <aside className="fixed bottom-24 right-3 z-50 w-[min(420px,calc(100vw-1.5rem))] overflow-hidden rounded-lg border border-border bg-popover/95 text-popover-foreground shadow-2xl backdrop-blur md:right-5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs"
      >
        <Bug className="size-3.5 text-cyan" />
        <span className="font-semibold">Flow debug</span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground" key={tick}>
          {summary.studioPlan !== "none" ? "Studio unlocked" : "Studio locked"}
        </span>
        <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      <div className="border-t border-border px-3 py-2 text-[11px] text-muted-foreground">
        Onboarded: <State value={summary.onboarded} /> · Trader: <State value={summary.traderSeeded} /> · Studio: <State value={summary.studioSeeded} /> · Plan: <span className="font-mono text-foreground">{summary.traderPlan} / {summary.studioPlan}</span>
        {latest && <div className="mt-1 truncate">Latest: {latest.message}</div>}
      </div>
      {open && (
        <div className="max-h-72 overflow-y-auto border-t border-border p-2">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Recent state changes</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => { clearDebugEvents(); setEvents([]); }}
            >
              <Trash2 className="mr-1 size-3" /> Clear
            </Button>
          </div>
          {events.length === 0 ? (
            <div className="rounded-md border border-dashed border-border p-3 text-center text-xs text-muted-foreground">No reset/subscription events yet.</div>
          ) : (
            <div className="space-y-1.5">
              {events.map((event) => (
                <div key={event.id} className="rounded-md border border-border bg-background/50 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-foreground">{event.message}</span>
                    <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{new Date(event.at).toLocaleTimeString()}</span>
                  </div>
                  <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{event.type}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </aside>
  );
}

function State({ value }: { value: boolean }) {
  return <span className={cn("font-mono", value ? "text-cyan" : "text-danger")}>{value ? "yes" : "no"}</span>;
}