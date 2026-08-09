import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";

/**
 * Inline jargon with a hover/tap definition. The term gets a subtle dotted
 * underline so users know there's an explanation behind it.
 *
 *   <Term name="sharpe" />            → renders "Sharpe" with its definition
 *   <Term name="stop">stop</Term>     → custom visible text, same definition
 */
export function Term({
  name,
  children,
  className,
}: {
  name: GlossaryKey;
  children?: React.ReactNode;
  className?: string;
}) {
  const entry = GLOSSARY[name];
  return (
    <TooltipProvider delayDuration={120}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            tabIndex={0}
            className={cn(
              "cursor-help underline decoration-dotted decoration-muted-foreground/50 underline-offset-2 outline-none focus-visible:decoration-foreground",
              className,
            )}
          >
            {children ?? entry.label}
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs text-pretty">
          <span className="font-semibold">{entry.label}.</span>{" "}
          <span className="text-muted-foreground">{entry.def}</span>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * A KPI / stat label that carries its own definition. Drop-in replacement for a
 * plain label string inside metric cards — keeps the same look but adds a dotted
 * underline + tooltip so terse labels like "Avg R" or "Max DD" are explained.
 */
export function MetricLabel({
  term,
  children,
  className,
}: {
  term: GlossaryKey;
  /** Override the visible label (defaults to the glossary label). */
  children?: React.ReactNode;
  className?: string;
}) {
  const entry = GLOSSARY[term];
  return (
    <TooltipProvider delayDuration={120}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            tabIndex={0}
            className={cn(
              "inline-flex cursor-help items-center gap-1 underline decoration-dotted decoration-muted-foreground/40 underline-offset-2 outline-none focus-visible:decoration-foreground",
              className,
            )}
          >
            {children ?? entry.label}
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs text-pretty">
          <span className="font-semibold">{entry.label}.</span>{" "}
          <span className="text-muted-foreground">{entry.def}</span>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
