import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

export function EmptyState({
  icon: Icon,
  headline,
  body,
  cta,
  className,
  compact,
}: {
  icon: LucideIcon;
  headline: string;
  body?: string;
  cta?: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <Card
      className={cn(
        "grid place-items-center gap-3 border-dashed border-border bg-elevated/40 text-center",
        compact ? "p-6" : "p-10",
        className,
      )}
    >
      <div className="grid size-12 place-items-center rounded-full border border-border bg-background/60 text-muted-foreground">
        <Icon className="size-5" strokeWidth={1.5} />
      </div>
      <div className="space-y-1">
        <div className="text-sm font-medium text-foreground">{headline}</div>
        {body && <div className="mx-auto max-w-md text-xs text-muted-foreground">{body}</div>}
      </div>
      {cta && <div className="mt-1">{cta}</div>}
    </Card>
  );
}
