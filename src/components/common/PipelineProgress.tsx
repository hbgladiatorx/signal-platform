import { cn } from "@/lib/utils";
import type { PipelineStage } from "@/lib/types";
import { Check } from "lucide-react";

const STAGES: PipelineStage[] = [
  "Draft", "Backtested", "Out-of-Sample Passed", "Forward Testing", "Live", "Submitted", "Published",
];

export function PipelineProgress({ current, className }: { current: PipelineStage; className?: string }) {
  const idx = STAGES.indexOf(current);
  const safeIdx = idx === -1 ? 0 : idx;
  return (
    <div className={cn("flex items-center gap-1", className)}>
      {STAGES.map((s, i) => {
        const done = i < safeIdx;
        const cur = i === safeIdx;
        return (
          <div key={s} className="flex items-center gap-1">
            <div className={cn(
              "flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] font-mono whitespace-nowrap",
              done && "border-violet/30 bg-violet/10 text-violet",
              cur && "border-violet bg-violet text-violet-foreground",
              !done && !cur && "border-border bg-muted/20 text-muted-foreground",
            )}>
              {done && <Check className="size-3" />} {s}
            </div>
            {i < STAGES.length - 1 && <div className={cn("h-px w-3", i < safeIdx ? "bg-violet" : "bg-border")} />}
          </div>
        );
      })}
    </div>
  );
}
