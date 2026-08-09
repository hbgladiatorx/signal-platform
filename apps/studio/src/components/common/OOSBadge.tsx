import { ShieldCheck, ShieldAlert, ShieldQuestion } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { PipelineStage, Strategy } from "@/lib/types";

export type OOSVerdict = "validated" | "marginal" | "not-validated";

// Pipeline stages that mean the edge cleared out-of-sample / forward testing.
const OOS_PASSED_STAGES: PipelineStage[] = [
  "Out-of-Sample Passed",
  "Forward Testing",
  "Live",
  "Published",
];

/**
 * Honest out-of-sample verdict, driven purely by real data:
 *   - `forward_win_rate` (mapped to `stats.winRate`) — the forward/OOS win rate.
 *   - `edgeVerified` / `stage` — the backend's edge-gate result (gate_status ≥ 5).
 *
 * We never fabricate an OOS number. If there's no forward result and the gate
 * hasn't been cleared, the verdict is "Not validated".
 */
export function oosVerdict(s: Strategy): OOSVerdict {
  const forwardWinRate = s.stats.winRate; // fraction; 0 when the field is absent
  const hasForward = forwardWinRate > 0;
  const passedGate = s.edgeVerified || OOS_PASSED_STAGES.includes(s.stage);

  if (passedGate) return "validated";
  if (hasForward) return "marginal";
  return "not-validated";
}

const CONFIG: Record<
  OOSVerdict,
  { label: string; className: string; Icon: typeof ShieldCheck }
> = {
  validated: {
    label: "Validated OOS",
    className: "border-gold/40 bg-gold/10 text-gold",
    Icon: ShieldCheck,
  },
  marginal: {
    label: "Marginal",
    className: "border-options/40 bg-options/10 text-options",
    Icon: ShieldAlert,
  },
  "not-validated": {
    label: "Not validated",
    className: "border-border bg-muted/30 text-muted-foreground",
    Icon: ShieldQuestion,
  },
};

function detail(verdict: OOSVerdict, s: Strategy): string {
  const fwr = s.stats.winRate;
  const pct = fwr > 0 ? `${(fwr * 100).toFixed(0)}%` : null;
  switch (verdict) {
    case "validated":
      return pct
        ? `Cleared Bayn's edge gate. Forward win rate: ${pct}.`
        : "Cleared Bayn's out-of-sample edge gate.";
    case "marginal":
      return pct
        ? `Forward win rate: ${pct}, but the edge gate isn't cleared yet.`
        : "Forward-tested, but the edge gate isn't cleared yet.";
    case "not-validated":
      return "No out-of-sample or forward results yet — edge unverified.";
  }
}

/** Compact OOS-validation verdict for strategy and catalog cards. */
export function OOSBadge({ strategy, className }: { strategy: Strategy; className?: string }) {
  const verdict = oosVerdict(strategy);
  const { label, className: tone, Icon } = CONFIG[verdict];
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "inline-flex cursor-help items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold",
              tone,
              className,
            )}
          >
            <Icon className="size-3.5" />
            {label}
            {verdict === "validated" && <span aria-hidden> ✓</span>}
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs bg-popover">
          <p className="text-xs text-muted-foreground">{detail(verdict, strategy)}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
