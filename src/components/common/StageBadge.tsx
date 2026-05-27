import type { PipelineStage } from "@/lib/types";
import { cn } from "@/lib/utils";

const stageColors: Record<PipelineStage, string> = {
  "Draft": "border-border bg-muted/30 text-muted-foreground",
  "Backtested": "border-cyan/30 bg-cyan/10 text-cyan",
  "Out-of-Sample Passed": "border-gold/30 bg-gold/10 text-gold",
  "Forward Testing": "border-options/30 bg-options/10 text-options",
  "Live": "border-futures/30 bg-futures/10 text-futures",
  "Submitted": "border-violet/30 bg-violet/10 text-violet",
  "Under Review": "border-violet/30 bg-violet/10 text-violet",
  "Published": "border-futures/30 bg-futures/15 text-futures",
  "Rejected": "border-danger/30 bg-danger/10 text-danger",
};

export function StageBadge({ stage, className }: { stage: PipelineStage; className?: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-mono", stageColors[stage], className)}>
      {stage}
    </span>
  );
}
