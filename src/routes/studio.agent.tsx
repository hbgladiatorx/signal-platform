import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { AgentChat } from "@/components/agent/AgentChat";
import { DeployabilityBadge, MCPMiniStatus } from "@/components/agent/AgentConnections";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { buildGraphFromPrompt } from "@/lib/api/agent";
import { ArrowRight } from "lucide-react";

export const Route = createFileRoute("/studio/agent")({
  head: () => ({ meta: [{ title: "Agent — Bayn Studio" }] }),
  component: StudioAgent,
});

function StudioAgent() {
  const navigate = useNavigate();
  const [lastBuild, setLastBuild] = useState<ReturnType<typeof buildGraphFromPrompt> | null>(null);

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Build with AI</h1>
          <p className="text-sm text-muted-foreground">Describe a strategy in plain English. I'll wire it on the canvas.</p>
        </div>
        <MCPMiniStatus />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <div className="h-[640px]">
          <AgentChat mode="studio" onGraph={(g) => setLastBuild(g)} />
        </div>

        <div className="space-y-3">
          <div className="text-xs font-mono uppercase tracking-wider text-muted-foreground">Latest build</div>
          {lastBuild ? (
            <Card className="space-y-3 border-violet/30 bg-elevated p-4">
              <div>
                <div className="text-sm font-semibold">{lastBuild.name}</div>
                <div className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-violet">{lastBuild.assetClass}</div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-md border border-border bg-background p-2"><div className="text-muted-foreground">Nodes</div><div className="font-mono">{lastBuild.graph.nodes.length}</div></div>
                <div className="rounded-md border border-border bg-background p-2"><div className="text-muted-foreground">Edges</div><div className="font-mono">{lastBuild.graph.edges.length}</div></div>
              </div>
              <DeployabilityBadge stage="draft" />
              <p className="text-xs text-muted-foreground">Run a backtest to unlock out-of-sample.</p>
              <Button size="sm" className="w-full bg-violet text-violet-foreground hover:bg-violet/90"
                onClick={() => navigate({ to: "/studio/builder/$id", params: { id: "new" }, search: { ai: encodeURIComponent(JSON.stringify(lastBuild)) } as never })}>
                Open in builder <ArrowRight className="ml-1 size-3.5" />
              </Button>
            </Card>
          ) : (
            <Card className="border-dashed border-border bg-elevated p-4 text-xs text-muted-foreground">
              Pick a prompt chip or write your own — I'll build the graph, then you can open it in the builder.
            </Card>
          )}

          <Card className="border-border bg-elevated p-4">
            <div className="mb-2 text-xs font-mono uppercase tracking-wider text-muted-foreground">Deployability pipeline</div>
            <div className="space-y-1.5">
              {(["draft","backtested","oos","forward","deployable","eligible"] as const).map((s) => (
                <DeployabilityBadge key={s} stage={s} />
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
