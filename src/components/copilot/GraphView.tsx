// Read-only node-graph view for the copilot workspace. Shows the strategy the
// copilot built/edited. Editing happens by prompting the copilot, not by hand —
// so this canvas is non-interactive (pan/zoom only).
import { useQuery } from "@tanstack/react-query";
import ReactFlow, { Background, Controls, MiniMap, type Edge, type Node } from "reactflow";
import { Loader2 } from "lucide-react";
import { StrategyNode, type StrategyNodeData } from "@/components/studio/StrategyNode";
import { getDevStrategy } from "@/lib/api/studio";
import type { StrategyGraph } from "@/lib/types";

const nodeTypes = { strategyNode: StrategyNode };

function toRFNodes(graph: StrategyGraph): Node<StrategyNodeData>[] {
  return graph.nodes.map((n) => ({
    id: n.id,
    type: "strategyNode",
    position: n.position,
    data: { category: n.category, label: n.label, nodeType: n.type, config: n.data },
  }));
}
function toRFEdges(graph: StrategyGraph): Edge[] {
  return graph.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourceHandle,
    targetHandle: e.targetHandle,
    animated: true,
  }));
}

export function GraphView({ strategyId }: { strategyId: string }) {
  const { data: strategy, isLoading } = useQuery({
    queryKey: ["devStrategy", strategyId],
    queryFn: () => getDevStrategy(strategyId),
  });

  if (isLoading) {
    return (
      <div className="grid h-full place-items-center text-muted-foreground">
        <Loader2 className="size-5 animate-spin" />
      </div>
    );
  }
  const graph = strategy?.graph;
  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="grid h-full place-items-center px-6 text-center text-sm text-muted-foreground">
        No node graph yet — ask the copilot to build a strategy and it'll appear here.
      </div>
    );
  }

  return (
    <div className="relative h-full">
      <div className="pointer-events-none absolute left-3 top-3 z-10 flex items-center gap-1.5 rounded-md border border-border bg-elevated/90 px-2.5 py-1.5 text-[10px] font-mono uppercase tracking-wider shadow-sm backdrop-blur">
        <span className="text-stocks">Data</span><span className="text-muted-foreground">→</span>
        <span className="text-futures">Indicator</span><span className="text-muted-foreground">→</span>
        <span className="text-gold">Logic</span><span className="text-muted-foreground">→</span>
        <span className="text-crypto">Risk</span><span className="text-muted-foreground">→</span>
        <span className="text-violet">Signal</span>
      </div>
      <ReactFlow
        nodes={toRFNodes(graph)}
        edges={toRFEdges(graph)}
        nodeTypes={nodeTypes}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ animated: true, style: { stroke: "var(--violet)", strokeWidth: 2 } }}
      >
        <Background gap={16} size={1} color="oklch(1 0 0 / 5%)" />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => {
            const cat = (n.data as StrategyNodeData | undefined)?.category;
            return cat === "signal" ? "#8b5cf6" : cat === "risk" ? "#f59e0b" : cat === "logic" ? "#eab308" : cat === "indicator" ? "#22c55e" : "#3b82f6";
          }}
          maskColor="oklch(0.145 0.005 270 / 70%)"
        />
      </ReactFlow>
    </div>
  );
}
