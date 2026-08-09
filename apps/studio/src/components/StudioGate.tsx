import { Link, useRouterState } from "@tanstack/react-router";
import { Lock, Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getCurrentPlan } from "@/lib/api/billing";

/**
 * Gates the /studio subtree. Traders without a Studio plan see an upsell
 * card with two paths: add Studio from Settings, or go straight to pricing.
 */
export function StudioGate({ children }: { children: React.ReactNode }) {
  const plan = getCurrentPlan();
  const pathname = useRouterState({ select: (r) => r.location.pathname });
  if (pathname === "/studio/pricing") return <>{children}</>;
  if (plan.developer) return <>{children}</>;

  return (
    <div className="grid min-h-screen place-items-center bg-background p-6">
      <Card className="max-w-lg border-violet/30 bg-elevated p-8 text-center">
        <div className="mx-auto mb-4 grid size-12 place-items-center rounded-full bg-violet/15 text-violet">
          <Lock className="size-5" />
        </div>
        <h1 className="text-xl font-semibold tracking-tight">Studio isn't on your plan</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Studio is the private strategy lab — node-based builder, backtesting, forward
          tests, and personal signal feed. Add a Studio plan to your account to unlock it.
        </p>
        <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
          <Button asChild className="bg-violet text-violet-foreground hover:bg-violet/90">
            <Link to="/studio/pricing">
              <Sparkles className="mr-1.5 size-4" /> View Studio plans
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/app/settings">Manage plan in Settings</Link>
          </Button>
        </div>
        <div className="mt-6 border-t border-border pt-4 text-xs text-muted-foreground">
          You'll keep your Trader account. Studio is added on top.
        </div>
      </Card>
    </div>
  );
}
