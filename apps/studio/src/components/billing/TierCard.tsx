import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Tier, Billing } from "@/lib/api/billing";
import { priceFor } from "@/lib/api/billing";
import { cn } from "@/lib/utils";

export type TierCardProps = {
  tier: Tier;
  billing: Billing;
  accent: "emerald" | "cyan" | "violet";
  current?: boolean;
  onSelect?: (tierId: Tier["id"]) => void;
  ctaOverride?: string;
};

export function TierCard({ tier, billing, accent, current, onSelect, ctaOverride }: TierCardProps) {
  const { perMonth, annual } = priceFor(tier, billing);
  const highlight = tier.highlight;
  const accentColor =
    accent === "violet" ? "var(--violet)" :
    accent === "cyan" ? "var(--cyan)" : "var(--emerald-glow)";

  return (
    <div
      className={cn(
        "relative flex flex-col rounded-2xl border p-7",
      )}
      style={{
        background: highlight
          ? `linear-gradient(180deg, color-mix(in oklab, ${accentColor} 14%, var(--elevated)), var(--elevated))`
          : "var(--elevated)",
        borderColor: highlight
          ? `color-mix(in oklab, ${accentColor} 55%, var(--border))`
          : current
          ? `color-mix(in oklab, ${accentColor} 50%, var(--border))`
          : "var(--border)",
        boxShadow: highlight
          ? `0 30px 80px -30px color-mix(in oklab, ${accentColor} 50%, transparent)`
          : undefined,
      }}
    >
      {highlight && (
        <div
          className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full px-3 py-1 text-[10px] font-semibold uppercase tracking-wider"
          style={{ background: accentColor, color: "var(--background)" }}
        >
          Most popular
        </div>
      )}
      {current && (
        <div className="absolute right-4 top-4 rounded-full border border-border bg-background px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Current plan
        </div>
      )}

      <div className="mb-1 text-sm font-medium text-muted-foreground">{tier.name}</div>
      <p className="mb-4 text-xs text-muted-foreground">{tier.blurb}</p>

      <div className="flex items-end gap-1">
        <span
          className="text-5xl font-bold"
          style={{ fontFamily: "var(--font-landing-display)", letterSpacing: "-0.025em" }}
        >
          ${perMonth.toLocaleString()}
        </span>
        <span className="mb-2 text-sm text-muted-foreground">/mo</span>
      </div>
      <div className="mt-1 text-[11px] text-muted-foreground">
        {billing === "annual" ? `$${annual.toLocaleString()} billed annually` : `Billed monthly`}
      </div>

      <Button
        onClick={() => onSelect?.(tier.id)}
        className="mt-6 h-11 w-full"
        style={
          highlight || current
            ? { background: accentColor, color: "var(--background)" }
            : { background: "transparent", border: "1px solid var(--border)", color: "var(--foreground)" }
        }
      >
        {ctaOverride ?? (current ? "Manage plan" : tier.cta)}
      </Button>

      <ul className="mt-7 space-y-2.5 text-sm">
        {tier.features.map((f) => (
          <li key={f.label} className="flex items-start gap-2.5">
            <Check className="mt-0.5 size-4 shrink-0" style={{ color: accentColor }} />
            <span className={cn("text-foreground/90", f.emphasis && "font-medium text-foreground")}>
              {f.label}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
