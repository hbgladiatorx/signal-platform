import { tiersFor, addonsFor, type Audience, type Billing, type TierId } from "@/lib/api/billing";
import { TierCard } from "./TierCard";
import { AddOnList } from "./AddOnList";

export function PricingTable({
  audience, billing, currentTier, activeAddOns = [], onSelect, onToggleAddOn,
}: {
  audience: Audience;
  billing: Billing;
  currentTier?: TierId | null;
  activeAddOns?: string[];
  onSelect?: (id: TierId) => void;
  onToggleAddOn?: (id: string) => void;
}) {
  const tiers = tiersFor(audience);
  const addons = addonsFor(audience);
  const accent = audience === "developer" ? "violet" : "cyan";

  return (
    <div className="space-y-10">
      <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
        {tiers.map((t) => (
          <TierCard
            key={t.id}
            tier={t}
            billing={billing}
            accent={accent}
            current={currentTier === t.id}
            onSelect={onSelect}
          />
        ))}
      </div>

      <div>
        <div className="mb-3 flex items-baseline justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            {audience === "developer" ? "Studio add-ons" : "Trader add-ons"}
          </h3>
          <p className="text-xs text-muted-foreground">
            Stackable on any tier. Toggle anytime.
          </p>
        </div>
        <AddOnList
          addons={addons}
          activeIds={activeAddOns}
          currentTier={currentTier ?? null}
          accent={accent}
          onToggle={onToggleAddOn}
        />
      </div>
    </div>
  );
}
