import { cn } from "@/lib/utils";
import { Info } from "lucide-react";

const TEXT = "Past performance does not predict future results. Bayn is not a brokerage and does not provide investment advice.";

export function Disclaimer({ variant = "inline", className }: { variant?: "inline" | "banner" | "card"; className?: string }) {
  if (variant === "banner") {
    return (
      <div className={cn("flex items-start gap-2 rounded-lg border border-gold/30 bg-gold/5 px-4 py-3 text-sm text-gold/90", className)}>
        <Info className="mt-0.5 size-4 shrink-0" />
        <p>{TEXT} You are responsible for every trade you take.</p>
      </div>
    );
  }
  if (variant === "card") {
    return (
      <p className={cn("text-[11px] leading-relaxed text-muted-foreground", className)}>
        Past results do not predict future ones. — Bayn
      </p>
    );
  }
  return <p className={cn("text-xs text-muted-foreground", className)}>{TEXT}</p>;
}
