import { createFileRoute } from "@tanstack/react-router";
import { AgentChat, TraderContextPanel } from "@/components/agent/AgentChat";
import { Card } from "@/components/ui/card";
import { ChevronDown, ChevronUp, Workflow } from "lucide-react";
import { useState } from "react";
import { MCPMiniStatus } from "@/components/agent/AgentConnections";

export const Route = createFileRoute("/app/agent")({
  head: () => ({ meta: [{ title: "Agent — Bayn" }] }),
  component: TraderAgent,
});

function TraderAgent() {
  const [loopOpen, setLoopOpen] = useState(true);
  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Agent</h1>
          <p className="text-sm text-muted-foreground">Analyze your trades. Action handed to your agentic loop.</p>
        </div>
        <MCPMiniStatus />
      </div>

      <Card className="border-border bg-elevated">
        <button onClick={() => setLoopOpen((o) => !o)} className="flex w-full items-center justify-between px-4 py-2.5 text-left">
          <div className="flex items-center gap-2 text-sm font-medium"><Workflow className="size-4 text-cyan" /> How the loop works</div>
          {loopOpen ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
        </button>
        {loopOpen && (
          <div className="space-y-2 border-t border-border px-4 py-3 text-sm">
            <ol className="ml-4 list-decimal space-y-1 text-muted-foreground">
              <li>Bayn's pipeline validates a strategy → publishes it → it fires a signal.</li>
              <li>Your AI agent (connected to <code className="font-mono text-foreground">https://agent.bayn.app/mcp</code>) reads the signal.</li>
              <li>The agent presents it to you with Bayn's verified context.</li>
              <li>On your confirmation, the agent places the order via <code className="font-mono text-foreground">https://agent.broker.com/mcp/trading</code>.</li>
              <li>Bayn tracks the outcome for your verified performance record.</li>
            </ol>
            <div className="rounded-md border border-warn/30 bg-warn/5 px-3 py-1.5 text-xs text-foreground/80">
              Bayn never executes. Brokerage never decides. <b className="text-warn">You always confirm.</b>
            </div>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div className="h-[640px]"><AgentChat mode="trader" /></div>
        <div className="space-y-3">
          <div className="text-xs font-mono uppercase tracking-wider text-muted-foreground">What I'm reading</div>
          <TraderContextPanel />
        </div>
      </div>
    </div>
  );
}
