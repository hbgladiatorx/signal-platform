import { Plus, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AddOn, TierId } from "@/lib/api/billing";

export function AddOnList({
  addons, activeIds = [], currentTier, accent = "emerald", onToggle,
}: {
  addons: AddOn[];
  activeIds?: string[];
  currentTier?: TierId | null;
  accent?: "emerald" | "cyan" | "violet";
  onToggle?: (id: string) => void;
}) {
  const accentColor =
    accent === "violet" ? "var(--violet)" :
    accent === "cyan" ? "var(--cyan)" : "var(--emerald-glow)";

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {addons.map((a) => {
        const included = currentTier ? a.includedOn?.includes(currentTier) : false;
        const restricted = currentTier && a.availableOn && !a.availableOn.includes(currentTier);
        const active = activeIds.includes(a.id);
        return (
          <div
            key={a.id}
            className="flex items-start justify-between gap-4 rounded-xl border border-border bg-elevated p-4"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold">{a.name}</h4>
                {included && (
                  <span
                    className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
                    style={{ background: `color-mix(in oklab, ${accentColor} 18%, transparent)`, color: accentColor }}
                  >
                    Included
                  </span>
                )}
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{a.description}</p>
              <div className="mt-2 text-sm font-medium" style={{ color: accentColor }}>
                ${a.price}
                <span className="ml-1 text-xs text-muted-foreground">{a.unit ?? "/ mo"}</span>
              </div>
            </div>
            <Button
              size="sm"
              variant={active ? "default" : "outline"}
              disabled={included || !!restricted}
              onClick={() => onToggle?.(a.id)}
              className="shrink-0"
              style={active ? { background: accentColor, color: "var(--background)" } : undefined}
            >
              {included ? (
                <>Included</>
              ) : restricted ? (
                <>Upgrade required</>
              ) : active ? (
                <><Check className="size-3.5" /> Added</>
              ) : (
                <><Plus className="size-3.5" /> Add</>
              )}
            </Button>
          </div>
        );
      })}
    </div>
  );
}
