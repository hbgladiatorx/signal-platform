import { cn } from "@/lib/utils";
import { ArrowUp, ArrowDown } from "lucide-react";
import type { Direction } from "@/lib/types";

export function DirectionPill({ direction, className }: { direction: Direction; className?: string }) {
  const long = direction === "LONG";
  return (
    <span className={cn(
      "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wider",
      long ? "bg-cyan/15 text-cyan border-cyan/30" : "bg-danger/15 text-danger border-danger/30",
      className,
    )}>
      {long ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />}
      {direction}
    </span>
  );
}
