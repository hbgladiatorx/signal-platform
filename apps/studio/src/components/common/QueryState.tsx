import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, Inbox } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/common/EmptyState";
import { cn } from "@/lib/utils";

/**
 * Minimal shape of a TanStack Query result that QueryState needs. Accepting a
 * subset (rather than the full UseQueryResult) keeps callers free to pass any
 * query without fighting the discriminated-union generics.
 */
export interface QueryLike<T> {
  data: T | undefined;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  refetch?: () => unknown;
}

interface QueryStateProps<T> {
  query: QueryLike<T>;
  children: (data: T) => ReactNode;
  /** Treat the resolved data as "empty" (defaults to empty-array detection). */
  isEmpty?: (data: T) => boolean;
  /** Custom loading UI; defaults to a few skeleton rows. */
  loading?: ReactNode;
  /** Number of skeleton rows for the default loading state. */
  skeletonRows?: number;
  emptyIcon?: LucideIcon;
  emptyHeadline?: string;
  emptyBody?: string;
  emptyCta?: ReactNode;
  errorHeadline?: string;
  className?: string;
}

function defaultIsEmpty<T>(data: T): boolean {
  return Array.isArray(data) && data.length === 0;
}

function LoadingSkeleton({ rows, className }: { rows: number; className?: string }) {
  return (
    <div className={cn("space-y-3", className)} aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-16 w-full rounded-lg" />
      ))}
    </div>
  );
}

/**
 * One consistent loading / empty / error wrapper for the ~23 data routes.
 * Renders a skeleton while loading, a visible error with a Retry button on
 * failure, a friendly empty state (optional CTA) when there's no data, and
 * otherwise the children with the resolved, non-empty data.
 */
export function QueryState<T>({
  query,
  children,
  isEmpty = defaultIsEmpty,
  loading,
  skeletonRows = 3,
  emptyIcon = Inbox,
  emptyHeadline = "Nothing here yet",
  emptyBody,
  emptyCta,
  errorHeadline = "Couldn't load this",
  className,
}: QueryStateProps<T>) {
  if (query.isLoading) {
    return <>{loading ?? <LoadingSkeleton rows={skeletonRows} className={className} />}</>;
  }

  if (query.isError || query.data === undefined) {
    const message = query.error instanceof Error ? query.error.message : "Something went wrong.";
    return (
      <Card className={cn("grid place-items-center gap-3 border-dashed border-danger/40 bg-elevated/40 p-10 text-center", className)}>
        <div className="grid size-12 place-items-center rounded-full border border-danger/40 bg-background/60 text-danger">
          <AlertTriangle className="size-5" strokeWidth={1.5} />
        </div>
        <div className="space-y-1">
          <div className="text-sm font-medium text-foreground">{errorHeadline}</div>
          <div className="mx-auto max-w-md text-xs text-muted-foreground">{message}</div>
        </div>
        {query.refetch && (
          <Button size="sm" variant="outline" className="mt-1" onClick={() => query.refetch?.()}>
            Retry
          </Button>
        )}
      </Card>
    );
  }

  if (isEmpty(query.data)) {
    return (
      <EmptyState
        icon={emptyIcon}
        headline={emptyHeadline}
        body={emptyBody}
        cta={emptyCta}
        className={className}
      />
    );
  }

  return <>{children(query.data)}</>;
}
