import { Component, type ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { AlertTriangle } from "lucide-react";

/**
 * Isolates a single results-card render failure so unexpected data in one
 * analysis/attribution/model card can never blank the whole backtest page.
 * Renders a compact fallback (with the message) instead of propagating.
 */
export class CardErrorBoundary extends Component<
  { children: ReactNode; label: string },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    // Surface to the console for debugging without crashing the page.
    console.error(`[${this.props.label}] render failed:`, error);
  }

  render() {
    if (this.state.error) {
      return (
        <Card className="border-danger/30 bg-elevated p-4">
          <div className="flex items-start gap-2 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" />
            <div>
              <div className="font-medium text-danger">Couldn’t render {this.props.label}</div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {this.state.error.message || "Unexpected data shape."} The rest of the
                results are unaffected.
              </p>
            </div>
          </div>
        </Card>
      );
    }
    return this.props.children;
  }
}
