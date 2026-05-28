import { cn } from "@/lib/utils";
import type { Billing } from "@/lib/api/billing";

export function BillingToggle({
  value, onChange, accent = "emerald",
}: { value: Billing; onChange: (v: Billing) => void; accent?: "emerald" | "cyan" | "violet" }) {
  const accentVar = accent === "violet" ? "var(--violet)" : accent === "cyan" ? "var(--cyan)" : "var(--emerald-glow)";
  return (
    <div className="inline-flex items-center gap-1 rounded-full border border-border bg-elevated p-1 text-sm">
      <button
        onClick={() => onChange("monthly")}
        className={cn(
          "rounded-full px-4 py-1.5 transition-colors",
          value === "monthly" ? "bg-background text-foreground" : "text-muted-foreground",
        )}
      >
        Monthly
      </button>
      <button
        onClick={() => onChange("annual")}
        className={cn(
          "flex items-center gap-2 rounded-full px-4 py-1.5 transition-colors",
          value === "annual" ? "bg-background text-foreground" : "text-muted-foreground",
        )}
      >
        Annual
        <span
          className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
          style={{ background: `color-mix(in oklab, ${accentVar} 22%, transparent)`, color: accentVar }}
        >
          2 mo free
        </span>
      </button>
    </div>
  );
}
