import { createFileRoute } from "@tanstack/react-router";
import { Card } from "@/components/ui/card";

export const Route = createFileRoute("/studio/docs")({
  head: () => ({ meta: [{ title: "Docs — Bayn Studio" }] }),
  component: DocsPage,
});

function DocsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4 md:p-6">
      <h1 className="text-2xl font-semibold tracking-tight">Studio docs</h1>
      <p className="text-sm text-muted-foreground font-mono">// how a strategy gets from idea to traders</p>
      <Card className="space-y-4 border-border bg-elevated p-6 text-sm leading-relaxed text-muted-foreground">
        {[
          ["1. Build", "Define your strategy as rules. Pick a market, write entry and exit conditions, and choose your risk envelope."],
          ["2. Backtest", "Bayn runs the strategy on full historical data with realistic fees and slippage. You see honest, measured numbers."],
          ["3. Out-of-sample", "Bayn re-runs the strategy on data it has never been optimized against. Strategies tuned to the past get caught here."],
          ["4. Forward test", "Bayn paper-trades the strategy on live data — no real money — to verify the historical numbers hold up."],
          ["5. Bayn review", "If the strategy clears the pipeline, a human at Bayn reviews it. Accepted strategies go into the catalog with a revenue share."],
        ].map(([title, body]) => (
          <div key={title}>
            <div className="font-mono text-cyan">{title}</div>
            <p className="mt-1">{body}</p>
          </div>
        ))}
      </Card>
    </div>
  );
}
