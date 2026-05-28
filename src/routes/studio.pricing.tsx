import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { BillingToggle } from "@/components/billing/BillingToggle";
import { PricingTable } from "@/components/billing/PricingTable";
import { UsageMeter } from "@/components/billing/UsageMeter";
import { PlanBadge } from "@/components/billing/PlanBadge";
import { getCurrentPlan, setCurrentPlan, getUsage, getTier, type Billing, type TierId } from "@/lib/api/billing";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";

export const Route = createFileRoute("/studio/pricing")({
  head: () => ({ meta: [{ title: "Studio plan — Bayn" }] }),
  component: StudioPricingPage,
});

function StudioPricingPage() {
  const [plan, setPlan] = useState(getCurrentPlan());
  const [billing, setBilling] = useState<Billing>(plan.billing);
  const studioUsage = getUsage().filter((u) => u.key.startsWith("studio"));

  const choose = (id: TierId) => {
    setCurrentPlan({ developer: id, billing });
    setPlan(getCurrentPlan());
    toast.success(`Studio plan: ${getTier(id)?.name}`);
  };
  const toggleAddOn = (id: string) => {
    const next = plan.activeAddOns.includes(id)
      ? plan.activeAddOns.filter((x) => x !== id)
      : [...plan.activeAddOns, id];
    setCurrentPlan({ activeAddOns: next });
    setPlan(getCurrentPlan());
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:px-6 md:py-10">
      <div className="mb-6 flex items-center gap-3">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/studio/settings"><ArrowLeft className="size-4" /> Settings</Link>
        </Button>
      </div>

      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-bold md:text-3xl" style={{ fontFamily: "var(--font-landing-display)" }}>
            Studio plan
          </h1>
          <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
            Current: <PlanBadge tier={plan.developer} /> · Billed {plan.billing}
          </p>
        </div>
        <BillingToggle value={billing} onChange={setBilling} accent="violet" />
      </div>

      <div className="mb-10 grid grid-cols-1 gap-3 md:grid-cols-3">
        {studioUsage.map((u) => (
          <UsageMeter key={u.key} label={u.label} current={u.current} limit={u.limit} period={u.period} accent="violet" />
        ))}
      </div>

      <PricingTable
        audience="developer"
        billing={billing}
        currentTier={plan.developer}
        activeAddOns={plan.activeAddOns}
        onSelect={choose}
        onToggleAddOn={toggleAddOn}
      />
    </div>
  );
}
