import { ReactFlow, Background, type Node, type Edge } from "reactflow";
import type { StrategyGraph, NodeCategory } from "@/lib/types";
import { cn } from "@/lib/utils";

const COLORS: Record<NodeCategory, string> = {
  data: "var(--color-stocks)",
  indicator: "var(--color-futures)",
  logic: "var(--color-gold)",
  risk: "var(--color-crypto)",
  signal: "var(--color-violet)",
};

function MiniNode({ data }: any) {
  return (
    <div className="rounded-md border border-border bg-elevated px-2 py-1 text-[10px]" style={{ borderLeft: `3px solid ${COLORS[data.category as NodeCategory]}` }}>
      {data.label}
    </div>
  );
}

const nodeTypes = { mini: MiniNode };

export function StrategyGraphPreview({ graph, className }: { graph: StrategyGraph; className?: string }) {
  const nodes: Node[] = graph.nodes.map((n) => ({
    id: n.id, type: "mini", position: n.position,
    data: { category: n.category, label: n.label },
    draggable: false, selectable: false,
  }));
  const edges: Edge[] = graph.edges.map((e) => ({ id: e.id, source: e.source, target: e.target, animated: false }));
  return (
    <div className={cn("h-32 w-full rounded-md border border-border bg-background/40", className)}>
      <ReactFlow
        nodes={nodes} edges={edges} nodeTypes={nodeTypes}
        fitView fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
        zoomOnScroll={false} zoomOnPinch={false} panOnDrag={false} preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={12} size={1} color="oklch(1 0 0 / 6%)" />
      </ReactFlow>
    </div>
  );
}
