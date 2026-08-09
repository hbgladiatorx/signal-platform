import { getTier, type TierId } from "@/lib/api/billing";
import { cn } from "@/lib/utils";

export function PlanBadge({ tier, className }: { tier: TierId | null; className?: string }) {
  if (!tier) {
    return (
      <span className={cn("rounded-full border border-border bg-elevated px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground", className)}>
        Free
      </span>
    );
  }
  const t = getTier(tier);
  const studio = tier.startsWith("studio-");
  return (
    <span
      className={cn("rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider", className)}
      style={{
        background: studio ? "color-mix(in oklab, var(--violet) 18%, transparent)" : "color-mix(in oklab, var(--cyan) 18%, transparent)",
        color: studio ? "var(--violet)" : "var(--cyan)",
      }}
    >
      {studio ? "Studio · " : ""}{t?.name ?? "Plan"}
    </span>
  );
}
