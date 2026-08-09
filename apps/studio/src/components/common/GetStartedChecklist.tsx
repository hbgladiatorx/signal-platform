import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Check, X, ArrowRight, Rocket } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useFollowedIds, getUserPerformance } from "@/lib/api";
import { useWatchlist, useDismissedChecklistItems } from "@/lib/user-prefs";

/**
 * The "soft prompt on your dashboard" that onboarding promises (StepDone in
 * onboarding.tsx). Wires up the previously-orphaned `checklist.dismissed` pref:
 * each item completes automatically as the user does the thing, and the whole
 * card can be dismissed once they've got their bearings.
 */

const DISMISS_KEY = "getStarted";

type Item = {
  id: string;
  title: string;
  hint: string;
  done: boolean;
  to: string;
  search?: Record<string, string>;
  cta: string;
};

export function GetStartedChecklist() {
  const [dismissed, setDismissed] = useDismissedChecklistItems();
  const [watchlist] = useWatchlist();
  const followed = useFollowedIds();
  // Light query just to know whether they've taken a signal yet.
  const perf = useQuery({ queryKey: ["perf", 365], queryFn: () => getUserPerformance(365) });

  const isDismissed = dismissed.includes(DISMISS_KEY);

  const items: Item[] = [
    {
      id: "follow",
      title: "Follow your first strategy",
      hint: "Pick a verified strategy from the catalog. Its live signals then land on your Home and Signals feed.",
      done: followed.length > 0,
      to: "/app/catalog",
      cta: "Browse catalog",
    },
    {
      id: "watchlist",
      title: "Build your watchlist",
      hint: "Add a few tickers you care about — they drive your market overview, charts, and news wire.",
      done: watchlist.length > 0,
      to: "/app/customize",
      search: { tab: "markets" },
      cta: "Add tickers",
    },
    {
      id: "signal",
      title: "Take your first signal",
      hint: "When a strategy fires, open the signal to see its entry, stop, and target — then log that you took it.",
      done: (perf.data?.kpis.totalTaken ?? 0) > 0,
      to: "/app/signals",
      cta: "View signals",
    },
  ];

  const doneCount = items.filter((i) => i.done).length;
  const allDone = doneCount === items.length;

  // Hide once everything's done or the user dismissed it.
  if (isDismissed || allDone) return null;

  return (
    <Card className="relative overflow-hidden border-cyan/30 bg-elevated p-5">
      <div
        aria-hidden
        className="pointer-events-none absolute -right-16 -top-16 size-48 rounded-full opacity-40 blur-3xl"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in oklab, var(--cyan) 40%, transparent), transparent)",
        }}
      />
      <div className="relative flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="grid size-9 place-items-center rounded-xl bg-cyan/15 text-cyan">
            <Rocket className="size-4.5" />
          </div>
          <div>
            <h2 className="text-sm font-semibold">Get started</h2>
            <p className="text-xs text-muted-foreground">
              {doneCount} of {items.length} done — a couple of steps to make Bayn yours.
            </p>
          </div>
        </div>
        <button
          onClick={() =>
            setDismissed((prev) => [...prev.filter((k) => k !== DISMISS_KEY), DISMISS_KEY])
          }
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
          aria-label="Dismiss get-started checklist"
        >
          <X className="size-4" />
        </button>
      </div>

      <ul className="relative mt-4 space-y-2">
        {items.map((item) => (
          <li
            key={item.id}
            className={cn(
              "flex items-center gap-3 rounded-lg border p-3 transition-colors",
              item.done ? "border-border/60 bg-background/30" : "border-border bg-background/40",
            )}
          >
            <span
              className={cn(
                "grid size-5 shrink-0 place-items-center rounded-full border",
                item.done
                  ? "border-cyan/40 bg-cyan/15 text-cyan"
                  : "border-border text-transparent",
              )}
            >
              <Check className="size-3" />
            </span>
            <div className="min-w-0 flex-1">
              <div
                className={cn(
                  "text-sm font-medium",
                  item.done && "text-muted-foreground line-through",
                )}
              >
                {item.title}
              </div>
              {!item.done && <p className="text-xs text-muted-foreground">{item.hint}</p>}
            </div>
            {!item.done && (
              <Button
                asChild
                size="sm"
                variant="ghost"
                className="shrink-0 gap-1 text-cyan hover:bg-cyan/10"
              >
                <Link to={item.to} search={item.search as never}>
                  {item.cta} <ArrowRight className="size-3.5" />
                </Link>
              </Button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
