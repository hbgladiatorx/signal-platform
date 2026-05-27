import { BadgeCheck } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip";

const stages = [
  "Backtested on full history",
  "Survived out-of-sample period",
  "Forward-tested on live data",
  "Reviewed by a human at Bayn",
  "Continuously monitored",
];

export function PipelineBadge({ compact = false }: { compact?: boolean }) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex cursor-help items-center gap-1 rounded-full border border-gold/40 bg-gold/10 px-2 py-0.5 text-[11px] font-semibold text-gold">
            <BadgeCheck className="size-3.5" />
            {compact ? "Verified" : "Edge Verified"}
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs bg-popover">
          <p className="mb-2 font-semibold text-foreground">5-stage edge pipeline</p>
          <ul className="space-y-1 text-xs">
            {stages.map((s, i) => (
              <li key={s} className="flex items-start gap-2">
                <span className="mt-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded-full bg-gold/20 text-[10px] text-gold">{i + 1}</span>
                <span className="text-muted-foreground">{s}</span>
              </li>
            ))}
          </ul>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
