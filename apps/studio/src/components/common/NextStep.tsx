import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, Rocket, PartyPopper, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useFollowedIds, getUserPerformance, getRecentSignals } from "@/lib/api";
import { useAccountSize, useDismissedChecklistItems } from "@/lib/user-prefs";

/**
 * The guided "Get to your first live trade" journey.
 *
 * One source of truth for "what should I do next?", driven entirely by real
 * account state. It renders an action-first next-step card plus a compact
 * progress rail, and completes each step automatically as the user does it.
 * When every step is done it collapses to a small, dismissible "all set" note.
 */

const DISMISS_KEY = "journeyComplete";

type Step = { id: string; title: string; hint: string; done: boolean; to: string; cta: string };

export function useJourney() {
  const followed = useFollowedIds();
  const [accountSize] = useAccountSize();
  const perf = useQuery({ queryKey: ["perf", 365], queryFn: () => getUserPerformance(365) });
  const recent = useQuery({ queryKey: ["recent"], queryFn: () => getRecentSignals(20) });

  const followedSet = new Set(followed);
  const hasSignal = (recent.data ?? []).some((s) => followedSet.has(s.strategyId));
  const hasTaken = (perf.data?.kpis.totalTaken ?? 0) > 0;

  const steps: Step[] = [
    {
      id: "setup", title: "Set your account size", done: accountSize > 0,
      hint: "It powers the suggested size on every signal. Takes a moment in Settings.",
      to: "/app/settings", cta: "Set it up",
    },
    {
      id: "follow", title: "Follow a strategy", done: followed.length > 0,
      hint: "Pick a verified strategy from the catalog — its live signals then appear here.",
      to: "/app/catalog", cta: "Browse catalog",
    },
    {
      id: "signal", title: "Get your first signal", done: hasSignal,
      hint: "A signal fires automatically when a strategy you follow meets its conditions.",
      to: "/app/signals", cta: "View signals",
    },
    {
      id: "trade", title: "Place & log your first trade", done: hasTaken,
      hint: "Open a signal, place it in your broker, then log the fill to start your track record.",
      to: "/app/signals", cta: "View signals",
    },
  ];

  const current = steps.find((s) => !s.done) ?? null;
  const doneCount = steps.filter((s) => s.done).length;
  return { steps, current, doneCount, total: steps.length, allDone: current === null };
}

/** Prominent next-step card + progress rail for the top of the Trader home. */
export function NextStep() {
  const { steps, current, doneCount, total, allDone } = useJourney();
  const [dismissed, setDismissed] = useDismissedChecklistItems();

  if (allDone) {
    if (dismissed.includes(DISMISS_KEY)) return null;
    return (
      <Card className="flex items-center gap-3 border-cyan/30 bg-cyan/5 p-4">
        <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-cyan/15 text-cyan">
          <PartyPopper className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">You're fully set up</div>
          <p className="text-xs text-muted-foreground">Signals from your strategies land here. Your performance is tracking.</p>
        </div>
        <button
          onClick={() => setDismissed((p) => [...p.filter((k) => k !== DISMISS_KEY), DISMISS_KEY])}
          className="rounded-md p-1 text-muted-foreground hover:bg-muted/40 hover:text-foreground"
          aria-label="Dismiss"
        >
          <X className="size-4" />
        </button>
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden border-cyan/30 bg-elevated p-6">
      <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-cyan">
            <Rocket className="size-3.5" /> Your next step · {doneCount} of {total} done
          </div>
          <h2 className="text-xl font-semibold tracking-tight">{current!.title}</h2>
          <p className="max-w-md text-sm text-muted-foreground">{current!.hint}</p>
        </div>
        <Button asChild size="lg" className="shrink-0 bg-cyan text-cyan-foreground hover:bg-cyan/90">
          <Link to={current!.to}>{current!.cta} <ArrowRight className="ml-1.5 size-4" /></Link>
        </Button>
      </div>

      {/* Progress rail */}
      <ol className="mt-6 flex flex-col gap-0 border-t border-border pt-4 sm:flex-row sm:gap-2">
        {steps.map((s, i) => {
          const isCurrent = s.id === current!.id;
          return (
            <li key={s.id} className="flex flex-1 items-center gap-2.5 py-1.5">
              <span
                className={cn(
                  "grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-semibold",
                  s.done ? "bg-cyan text-cyan-foreground"
                    : isCurrent ? "bg-cyan/15 text-cyan ring-2 ring-cyan/40"
                    : "bg-muted/40 text-muted-foreground",
                )}
              >
                {s.done ? <Check className="size-3.5" /> : i + 1}
              </span>
              <span className={cn("truncate text-xs", s.done ? "text-muted-foreground" : isCurrent ? "font-medium text-foreground" : "text-muted-foreground")}>
                {s.title}
              </span>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
