import { cn } from "@/lib/utils";
import { Check, X, Clock } from "lucide-react";
import type { SignalStatus } from "@/lib/types";

export function StatusPill({ status, className }: { status: SignalStatus; className?: string }) {
  if (status === "OPEN") {
    return (
      <span className={cn("inline-flex items-center rounded-md border border-cyan/30 bg-cyan/10 px-2 py-0.5 text-[11px] font-semibold text-cyan pulse-dot", className)}>
        OPEN
      </span>
    );
  }
  if (status === "HIT_TARGET") {
    return (
      <span className={cn("inline-flex items-center gap-1 rounded-md border border-futures/30 bg-futures/10 px-2 py-0.5 text-[11px] font-semibold text-futures", className)}>
        <Check className="size-3" /> TARGET
      </span>
    );
  }
  if (status === "HIT_STOP") {
    return (
      <span className={cn("inline-flex items-center gap-1 rounded-md border border-danger/30 bg-danger/10 px-2 py-0.5 text-[11px] font-semibold text-danger", className)}>
        <X className="size-3" /> STOP
      </span>
    );
  }
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-0.5 text-[11px] font-semibold text-muted-foreground", className)}>
      <Clock className="size-3" /> EXPIRED
    </span>
  );
}
