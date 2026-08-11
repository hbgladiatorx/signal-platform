import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Info } from "lucide-react";

/**
 * Info icon → popover with a plain-English "what this strategy does".
 * Prefers the natural-language description; falls back to the stored one.
 * Stops click propagation so it never triggers a row/card's own navigation.
 */
export function WhatItDoes({ text }: { text?: string }) {
  const body = text && text.trim()
    ? text.trim()
    : "No plain-English summary yet — open the strategy to see its exact rules.";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-6 shrink-0 text-muted-foreground hover:text-cyan"
          aria-label="What this strategy does"
          title="What it does"
          onClick={(e) => e.stopPropagation()}
        >
          <Info className="size-3.5" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="max-w-xs" onClick={(e) => e.stopPropagation()}>
        <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">What it does</div>
        <p className="text-sm leading-relaxed text-foreground/90">{body}</p>
      </PopoverContent>
    </Popover>
  );
}
