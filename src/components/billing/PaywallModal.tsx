import { useMemo } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  ArrowUpRight, Plus, RefreshCcw, Crown, Lock,
} from "lucide-react";
import { getEffectiveFollowedIds, subscribeToStrategy, unsubscribeFromStrategy } from "@/lib/api";
import {
  getCurrentPlan, getTotalSlots, getTier, isFreeStrategy,
  purchaseAddOn, upgradePlan, type TierId,
} from "@/lib/api/billing";
import { strategies } from "@/lib/mockData";

export function PaywallModal({
  strategyId,
  open,
  onOpenChange,
  onResolved,
}: {
  strategyId: string | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onResolved?: () => void;
}) {
  const strategy = useMemo(
    () => (strategyId ? strategies.find((s) => s.id === strategyId) : null),
    [strategyId],
  );
  const plan = getCurrentPlan();
  const total = getTotalSlots();
  const followed = getEffectiveFollowedIds();
  const followedNonFree = followed.filter((id) => !isFreeStrategy(id));
  const used = followedNonFree.length;

  const nextTier: TierId | null =
    plan.trader === null ? "trader-signal" :
    plan.trader === "trader-signal" ? "trader-edge" :
    plan.trader === "trader-edge" ? "trader-desk" : null;
  const nextTierMeta = nextTier ? getTier(nextTier) : null;

  const qc = useQueryClient();
  const handleResolve = async (toastMsg: string, followAfterPurchase = true) => {
    if (followAfterPurchase && strategyId && !getEffectiveFollowedIds().includes(strategyId)) {
      await subscribeToStrategy(strategyId);
    }
    qc.invalidateQueries({ queryKey: ["followed"] });
    qc.invalidateQueries({ queryKey: ["plan"] });
    toast.success(toastMsg);
    onOpenChange(false);
    onResolved?.();
  };

  const strategyName = strategy?.name ?? "this strategy";

  const unsub = useMutation({
    mutationFn: async (id: string) => {
      await unsubscribeFromStrategy(id);
      if (strategyId) await subscribeToStrategy(strategyId);
      return { ok: true };
    },
    onSuccess: () => handleResolve(`Now following ${strategyName}`, false),
  });

  if (!strategy) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl bg-elevated">
        <DialogHeader>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Lock className="size-3.5" />
            <span className="font-mono uppercase tracking-wider">Premium strategy</span>
          </div>
          <DialogTitle className="text-xl">Follow {strategy.name}</DialogTitle>
          <DialogDescription>
            You're using <span className="font-mono text-foreground">{used}</span> of{" "}
            <span className="font-mono text-foreground">{total === -1 ? "∞" : total}</span> premium slots.
            Pick a path to add this strategy.
          </DialogDescription>
        </DialogHeader>

        {/* Strategy summary chip */}
        <Card className="border-border bg-background/40 p-3">
          <div className="flex items-center justify-between gap-3 text-xs">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-foreground">{strategy.name}</div>
              <div className="truncate text-muted-foreground">{strategy.description}</div>
            </div>
            <div className="shrink-0 text-right font-mono text-muted-foreground">
              <div><span className="text-foreground">{strategy.stats.sharpe.toFixed(2)}</span> Sharpe</div>
              <div><span className="text-foreground">{(strategy.stats.winRate * 100).toFixed(0)}%</span> win</div>
            </div>
          </div>
        </Card>

        <div className="grid gap-3 md:grid-cols-3">
          {/* Path 1: Upgrade plan */}
          <PathCard
            icon={Crown}
            title="Upgrade plan"
            disabled={!nextTierMeta}
            subtitle={
              nextTierMeta
                ? `${nextTierMeta.name} — ${nextTierMeta.includedSlots === -1 ? "Unlimited" : nextTierMeta.includedSlots} slots`
                : "You're on the top tier"
            }
            price={nextTierMeta ? `$${nextTierMeta.monthly}/mo` : ""}
            cta="Upgrade"
            onClick={() => {
              if (!nextTier) return;
              upgradePlan(nextTier);
              void handleResolve(`Upgraded to ${nextTierMeta!.name} — now following ${strategy.name}`);
            }}
          />
          {/* Path 2: Add a slot */}
          <PathCard
            icon={Plus}
            title="Add a strategy slot"
            subtitle="One extra premium subscription, billed monthly."
            price="$99/mo"
            cta="Add slot"
            onClick={() => {
              purchaseAddOn("trader-extra-strategy");
              void handleResolve(`Slot added — now following ${strategy.name}`);
            }}
            footer={
              <button
                onClick={() => {
                  purchaseAddOn("trader-strategy-pack-5");
                  void handleResolve(`5-slot pack added — now following ${strategy.name}`);
                }}
                className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              >
                Or get 5 slots for $399/mo
              </button>
            }
          />
          {/* Path 3: Swap */}
          <PathCard
            icon={RefreshCcw}
            title="Swap a strategy"
            subtitle={
              followedNonFree.length === 0
                ? "No premium strategies to swap yet."
                : "Unfollow one to free a slot."
            }
            price=""
            cta=""
            disabled={followedNonFree.length === 0}
          >
            {followedNonFree.length > 0 && (
              <div className="space-y-1">
                {followedNonFree.slice(0, 4).map((id) => {
                  const s = strategies.find((x) => x.id === id);
                  if (!s) return null;
                  return (
                    <button
                      key={id}
                      disabled={unsub.isPending}
                      onClick={() => unsub.mutate(id)}
                      className="flex w-full items-center justify-between rounded-md border border-border bg-background/40 px-2 py-1.5 text-left text-[11px] transition-colors hover:border-cyan/40 hover:text-cyan"
                    >
                      <span className="truncate">{s.name}</span>
                      <span className="ml-2 shrink-0 text-muted-foreground">Unfollow</span>
                    </button>
                  );
                })}
              </div>
            )}
          </PathCard>
        </div>

        <div className="flex items-center justify-between border-t border-border pt-3">
          <Button asChild variant="ghost" size="sm">
            <Link to="/app/pricing">
              See all plans <ArrowUpRight className="ml-1 size-3.5" />
            </Link>
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            Maybe later
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function PathCard({
  icon: Icon, title, subtitle, price, cta, onClick, disabled, footer, children,
}: {
  icon: typeof Crown;
  title: string;
  subtitle: string;
  price: string;
  cta: string;
  onClick?: () => void;
  disabled?: boolean;
  footer?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <Card className="flex flex-col gap-2 border-border bg-background/40 p-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
        <Icon className="size-3.5 text-cyan" />
        {title}
      </div>
      <div className="text-[11px] text-muted-foreground">{subtitle}</div>
      {price && <div className="font-mono text-sm text-foreground">{price}</div>}
      {children}
      {cta && (
        <Button
          size="sm"
          disabled={disabled}
          onClick={onClick}
          className="mt-auto h-8 bg-cyan text-cyan-foreground hover:bg-cyan/90"
        >
          {cta}
        </Button>
      )}
      {footer && <div className="text-center">{footer}</div>}
    </Card>
  );
}
