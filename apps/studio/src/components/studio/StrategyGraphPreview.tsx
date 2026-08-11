import { ReactFlow, Background, Handle, Position, type Node, type Edge } from "reactflow";
import type { StrategyGraph, NodeCategory } from "@/lib/types";
import { cn } from "@/lib/utils";

const COLORS: Record<NodeCategory, string> = {
  data: "var(--color-stocks)",
  indicator: "var(--color-futures)",
  logic: "var(--color-gold)",
  risk: "var(--color-crypto)",
  signal: "var(--color-violet)",
};

// Handles must exist (and match the builder's ids "in"/"out") or ReactFlow has
// nowhere to attach edges — the connections silently disappear. Kept small and
// subtle since this is a read-only preview.
const miniHandle = "!size-1.5 !border-0 !bg-muted-foreground/50";

function MiniNode({ data }: any) {
  return (
    <div className="relative rounded-md border border-border bg-elevated px-2 py-1 text-[10px]" style={{ borderLeft: `3px solid ${COLORS[data.category as NodeCategory]}` }}>
      <Handle type="target" position={Position.Left} id="in" className={miniHandle} />
      {data.label}
      <Handle type="source" position={Position.Right} id="out" className={miniHandle} />
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
  const edges: Edge[] = graph.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    // Match the handle ids so edges attach to the right ports (fallback to the
    // builder defaults when the stored edge doesn't name them).
    sourceHandle: e.sourceHandle ?? "out",
    targetHandle: e.targetHandle ?? "in",
    animated: false,
    style: { stroke: "var(--muted-foreground)", strokeWidth: 1.5 },
  }));
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
