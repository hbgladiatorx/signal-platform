import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background, Controls, MiniMap, addEdge, applyEdgeChanges, applyNodeChanges,
  type Connection, type Edge, type Node, type OnNodesChange, type OnEdgesChange,
} from "reactflow";
import { useQuery } from "@tanstack/react-query";
import { getDevStrategy, getTemplates, saveStrategyGraph, runBacktest, ensureDevStrategyDraft } from "@/lib/api/studio";
import { advanceStage } from "@/lib/strategy-stage";
import { StrategyNode, type StrategyNodeData } from "@/components/studio/StrategyNode";
import { NodePalette, PALETTE, type PaletteNode } from "@/components/studio/NodePalette";
import { NodeInspector } from "@/components/studio/NodeInspector";
import { BacktestRunModal } from "@/components/studio/BacktestRunModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card } from "@/components/ui/card";
import { Save, PlayCircle, Rocket, CheckCircle2, AlertCircle, Download, ChevronDown, ChevronUp, FileCode, Sparkles, ChevronsLeftRight, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { AssetClass, StrategyGraph } from "@/lib/types";
import { AgentChat } from "@/components/agent/AgentChat";
import type { ChatMsg } from "@/lib/api/agent";


export const Route = createFileRoute("/studio/builder/$id")({
  head: () => ({ meta: [{ title: "Builder — Bayn Studio" }] }),
  component: Builder,
});

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
  return graph.edges.map((e) => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle, targetHandle: e.targetHandle, animated: true }));
}

function Builder() {
  const { id } = useParams({ from: "/studio/builder/$id" });
  const navigate = useNavigate();
  const isNew = id === "new";

  const { data: strategy } = useQuery({
    queryKey: ["devStrategy", id],
    queryFn: () => getDevStrategy(id),
    enabled: !isNew,
  });
  const { data: templates } = useQuery({ queryKey: ["templates"], queryFn: getTemplates });

  const [name, setName] = useState("Untitled strategy");
  const [assetClass, setAssetClass] = useState<AssetClass>("crypto");
  const [nodes, setNodes] = useState<Node<StrategyNodeData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showTemplates, setShowTemplates] = useState(isNew);
  const [showBacktest, setShowBacktest] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(true);
  const [logs, setLogs] = useState<Array<{ ts: string; level: "info" | "error" | "ok"; msg: string }>>([
    { ts: new Date().toISOString(), level: "info", msg: "Builder ready. Drag nodes from the palette or load a template." },
  ]);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [leftTab, setLeftTab] = useState<"ai" | "palette">("ai");
  const [aiHighlight, setAiHighlight] = useState<Set<string>>(new Set());
  const [sidebarWidth, setSidebarWidth] = useState(340);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const counter = useRef(0);

  // Drag-to-resize the AI / palette sidebar.
  const dragging = useRef(false);
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const next = Math.min(820, Math.max(260, e.clientX));
      setSidebarWidth(next);
    };
    const onUp = () => { dragging.current = false; document.body.style.cursor = ""; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, []);

  const getCurrentGraph = useCallback(() => {
    if (!nodes.length) return null;
    return {
      name,
      assetClass,
      nodes: nodes.map((n) => ({
        id: n.id, type: n.data.nodeType, category: n.data.category, label: n.data.label,
        position: n.position, data: n.data.config,
      })),
      edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle ?? undefined, targetHandle: e.targetHandle ?? undefined })),
    };
  }, [nodes, edges, name, assetClass]);

  const applyAIGraph = (g: NonNullable<ChatMsg["meta"]>["graph"]) => {
    if (!g) return;
    setName(g.name);
    setAssetClass(g.assetClass);
    setNodes([]); setEdges([]);
    const rfNodes = toRFNodes(g.graph);
    const rfEdges = toRFEdges(g.graph);
    const highlight = new Set<string>();
    // staggered placement ~150ms each
    rfNodes.forEach((n, i) => {
      setTimeout(() => {
        highlight.add(n.id);
        setAiHighlight(new Set(highlight));
        setNodes((prev) => [...prev, n]);
        setLogs((l) => [...l, { ts: new Date().toISOString(), level: "info", msg: `AI placed ${n.data.label}` }]);
      }, i * 150);
    });
    // edges after all nodes
    setTimeout(() => {
      setEdges(rfEdges);
      setLogs((l) => [...l, { ts: new Date().toISOString(), level: "ok", msg: `AI built ${rfNodes.length} nodes · ${rfEdges.length} edges` }]);
      setTimeout(() => setAiHighlight(new Set()), 2500);
    }, rfNodes.length * 150 + 200);
    counter.current = rfNodes.length;
  };

  /** Apply an AI tweak: patch node data in place, keep positions, highlight affected nodes. */
  const applyAITweak = (t: import("@/lib/api/agent").TweakResult) => {
    const byId = new Map(t.graph.nodes.map((n) => [n.id, n]));
    setName(t.name);
    setAssetClass(t.assetClass);
    setNodes((prev) => prev.map((rn) => {
      const updated = byId.get(rn.id);
      if (!updated) return rn;
      return { ...rn, data: { ...rn.data, label: updated.label, config: updated.data } };
    }));
    setAiHighlight(new Set(t.changedNodeIds));
    setLogs((l) => [
      ...l,
      ...t.changes.map((c) => ({ ts: new Date().toISOString(), level: "ok" as const, msg: `AI tweak: ${c}` })),
    ]);
    setTimeout(() => setAiHighlight(new Set()), 2500);
  };


  useEffect(() => {
    if (strategy) {
      setName(strategy.name);
      setAssetClass(strategy.assetClass);
      setNodes(toRFNodes(strategy.graph));
      setEdges(toRFEdges(strategy.graph));
      counter.current = strategy.graph.nodes.length;
    }
  }, [strategy]);

  const onNodesChange: OnNodesChange = useCallback((c) => setNodes((ns) => applyNodeChanges(c, ns)), []);
  const onEdgesChange: OnEdgesChange = useCallback((c) => setEdges((es) => applyEdgeChanges(c, es)), []);
  const onConnect = useCallback((conn: Connection) => {
    setEdges((es) => addEdge({ ...conn, animated: true }, es));
  }, []);

  const addNodeFromPalette = (p: PaletteNode) => {
    counter.current += 1;
    const id = `n${Date.now()}-${counter.current}`;
    const newNode: Node<StrategyNodeData> = {
      id, type: "strategyNode",
      position: { x: 200 + Math.random() * 200, y: 100 + Math.random() * 200 },
      data: { category: p.category, label: p.label, nodeType: p.type, config: { ...p.defaultData } },
    };
    setNodes((ns) => [...ns, newNode]);
    setLogs((l) => [...l, { ts: new Date().toISOString(), level: "info", msg: `Added node: ${p.label}` }]);
  };

  const updateNodeConfig = (nodeId: string, config: Record<string, unknown>) => {
    setNodes((ns) => ns.map((n) => n.id === nodeId ? { ...n, data: { ...n.data, config } } : n));
  };
  const deleteNode = (nodeId: string) => {
    setNodes((ns) => ns.filter((n) => n.id !== nodeId));
    setEdges((es) => es.filter((e) => e.source !== nodeId && e.target !== nodeId));
    if (selectedId === nodeId) setSelectedId(null);
  };

  const selectedNode = useMemo(() => nodes.find((n) => n.id === selectedId) ?? null, [nodes, selectedId]);

  const validate = () => {
    const errors: string[] = [];
    if (nodes.length === 0) errors.push("Graph is empty.");
    const hasEntry = nodes.some((n) => n.data.category === "signal");
    if (!hasEntry) errors.push("No signal output node — strategy will never fire.");
    const hasData = nodes.some((n) => n.data.category === "data");
    if (!hasData) errors.push("No data source — connect at least one Price/Volume node.");
    // disconnected
    const usedInEdge = new Set([...edges.map((e) => e.source), ...edges.map((e) => e.target)]);
    const orphans = nodes.filter((n) => !usedInEdge.has(n.id));
    if (orphans.length) errors.push(`${orphans.length} disconnected node(s).`);

    if (errors.length) {
      errors.forEach((e) => setLogs((l) => [...l, { ts: new Date().toISOString(), level: "error", msg: e }]));
      toast.error(`Validation found ${errors.length} issue(s)`);
    } else {
      setLogs((l) => [...l, { ts: new Date().toISOString(), level: "ok", msg: "✓ Validation passed. Graph is consistent." }]);
      toast.success("Validation passed");
    }
  };

  const handleSave = async () => {
    setSaveStatus("saving");
    const graph: StrategyGraph = {
      nodes: nodes.map((n) => ({
        id: n.id, type: n.data.nodeType, category: n.data.category, label: n.data.label,
        position: n.position, data: n.data.config,
      })),
      edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle ?? undefined, targetHandle: e.targetHandle ?? undefined })),
    };
    await saveStrategyGraph(id, graph);
    setSaveStatus("saved");
    setLogs((l) => [...l, { ts: new Date().toISOString(), level: "ok", msg: `Saved ${nodes.length} nodes, ${edges.length} edges.` }]);
    setTimeout(() => setSaveStatus("idle"), 2000);
  };

  const handleRunBacktest = async (params: any) => {
    setLogs((l) => [...l, { ts: new Date().toISOString(), level: "info", msg: `Backtest started: ${params.startDate} → ${params.endDate}, $${params.capital}` }]);
    // Ensure a real DevStrategy exists so the results page can resolve it.
    const graph: StrategyGraph = {
      nodes: nodes.map((n) => ({
        id: n.id, type: n.data.nodeType, category: n.data.category, label: n.data.label,
        position: n.position, data: n.data.config,
      })),
      edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle ?? undefined, targetHandle: e.targetHandle ?? undefined })),
    };
    const draft = await ensureDevStrategyDraft({ id: isNew ? undefined : id, name, assetClass, graph });
    const run = await runBacktest(draft.id, params);
    advanceStage(draft.id, "backtested");
    setLogs((l) => [...l, { ts: new Date().toISOString(), level: "ok", msg: `Backtest ${run.id} completed. Opening results…` }]);
    toast.success("Backtest finished — opening results");
    return run;
  };

  const handleExport = () => {
    const blob = new Blob([JSON.stringify({ name, assetClass, nodes, edges }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${name.toLowerCase().replace(/\s+/g, "-")}.json`; a.click();
    URL.revokeObjectURL(url);
  };

  const loadTemplate = (tplId: string) => {
    const tpl = templates?.find((t) => t.id === tplId);
    if (!tpl) return;
    setName(tpl.name);
    setAssetClass(tpl.assetClass);
    setNodes(toRFNodes(tpl.graph));
    setEdges(toRFEdges(tpl.graph));
    counter.current = tpl.graph.nodes.length;
    setShowTemplates(false);
    setLogs((l) => [...l, { ts: new Date().toISOString(), level: "info", msg: `Loaded template: ${tpl.name}` }]);
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      {/* Top bar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-elevated px-3 py-2">
        <Input value={name} onChange={(e) => setName(e.target.value)} className="h-9 w-72 bg-background font-medium" />
        <Select value={assetClass} onValueChange={(v: any) => setAssetClass(v)}>
          <SelectTrigger className="h-9 w-32 bg-background"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="stocks">Stocks</SelectItem>
            <SelectItem value="crypto">Crypto</SelectItem>
            <SelectItem value="options">Options</SelectItem>
            <SelectItem value="futures">Futures</SelectItem>
          </SelectContent>
        </Select>
        <div className="ml-2 flex items-center gap-1 text-xs text-muted-foreground">
          {saveStatus === "saving" && "Saving…"}
          {saveStatus === "saved" && <><CheckCircle2 className="size-3 text-futures" /> Saved</>}
        </div>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => setShowTemplates(true)}><FileCode className="mr-1 size-4" /> Templates</Button>
          <Button size="sm" variant="outline" onClick={handleExport}><Download className="mr-1 size-4" /> Export JSON</Button>
          <Button size="sm" variant="outline" onClick={validate}>Validate</Button>
          <Button size="sm" variant="outline" onClick={handleSave}><Save className="mr-1 size-4" /> Save</Button>
          <Button size="sm" className="bg-cyan text-cyan-foreground hover:bg-cyan/90" onClick={() => setShowBacktest(true)}>
            <PlayCircle className="mr-1 size-4" /> Run Backtest
          </Button>
          <Button size="sm" className="bg-violet text-violet-foreground hover:bg-violet/90"
            onClick={() => { toast.success("Deployed to live forward test"); setLogs((l) => [...l, { ts: new Date().toISOString(), level: "ok", msg: "Strategy deployed to live forward test." }]); }}>
            <Rocket className="mr-1 size-4" /> Deploy Live
          </Button>
        </div>
      </div>

      {/* Workspace */}
      <div className="flex min-h-0 flex-1">
        {/* Left sidebar: AI Builder ↔ Palette tabs (resizable) */}
        {!sidebarCollapsed && (
          <>
            <div
              className="flex shrink-0 flex-col border-r border-border bg-sidebar"
              style={{ width: sidebarWidth }}
            >
              <div className="flex items-center border-b border-border bg-elevated">
                <button
                  onClick={() => setLeftTab("ai")}
                  className={cn(
                    "flex flex-1 items-center justify-center gap-1.5 px-3 py-2.5 text-[11px] font-mono uppercase tracking-wider transition-colors",
                    leftTab === "ai"
                      ? "border-b-2 border-violet bg-violet/5 text-violet"
                      : "border-b-2 border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Sparkles className="size-3.5" /> AI Builder
                </button>
                <button
                  onClick={() => setLeftTab("palette")}
                  className={cn(
                    "flex flex-1 items-center justify-center gap-1.5 px-3 py-2.5 text-[11px] font-mono uppercase tracking-wider transition-colors",
                    leftTab === "palette"
                      ? "border-b-2 border-cyan bg-cyan/5 text-cyan"
                      : "border-b-2 border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  <FileCode className="size-3.5" /> Palette
                </button>
                <button
                  onClick={() => setSidebarWidth((w) => (w < 600 ? 720 : 340))}
                  title="Expand / shrink"
                  className="px-2 py-2.5 text-muted-foreground hover:text-foreground"
                >
                  <ChevronsLeftRight className="size-3.5" />
                </button>
                <button
                  onClick={() => setSidebarCollapsed(true)}
                  title="Collapse sidebar"
                  className="px-2 py-2.5 text-muted-foreground hover:text-foreground"
                >
                  <PanelLeftClose className="size-3.5" />
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-hidden">
                {leftTab === "ai" ? (
                  <AgentChat
                    mode="studio"
                    compact
                    getCurrentGraph={getCurrentGraph}
                    onGraph={(g) => g && applyAIGraph(g)}
                    onTweak={(t) => applyAITweak(t)}
                  />
                ) : (
                  <NodePalette onAdd={addNodeFromPalette} />
                )}
              </div>
            </div>
            {/* drag handle */}
            <div
              onMouseDown={() => { dragging.current = true; document.body.style.cursor = "col-resize"; }}
              className="w-1 shrink-0 cursor-col-resize bg-border hover:bg-violet/40"
              title="Drag to resize"
            />
          </>
        )}
        {sidebarCollapsed && (
          <button
            onClick={() => setSidebarCollapsed(false)}
            className="flex w-8 shrink-0 items-center justify-center border-r border-border bg-sidebar text-muted-foreground hover:text-foreground"
            title="Expand sidebar"
          >
            <PanelLeftOpen className="size-4" />
          </button>
        )}

        {/* Canvas + console */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="relative flex-1">
            {/* Flow legend */}
            <div className="pointer-events-none absolute left-3 top-3 z-10 flex items-center gap-1.5 rounded-md border border-border bg-elevated/90 px-2.5 py-1.5 text-[10px] font-mono uppercase tracking-wider shadow-sm backdrop-blur">
              <span className="text-stocks">1·Data</span><span className="text-muted-foreground">→</span>
              <span className="text-futures">2·Indicator</span><span className="text-muted-foreground">→</span>
              <span className="text-gold">3·Logic</span><span className="text-muted-foreground">→</span>
              <span className="text-crypto">4·Risk</span><span className="text-muted-foreground">→</span>
              <span className="text-violet">5·Signal</span>
            </div>
            <ReactFlow
              nodes={nodes.map((n) => aiHighlight.has(n.id) ? { ...n, className: "ai-placed" } : n)}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={(_, n) => setSelectedId(n.id)}
              onPaneClick={() => setSelectedId(null)}
              fitView
              defaultEdgeOptions={{ animated: true, style: { stroke: "var(--violet)", strokeWidth: 2 } }}
              connectionLineStyle={{ stroke: "var(--violet)", strokeWidth: 2 }}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={16} size={1} color="oklch(1 0 0 / 5%)" />
              <Controls />
              <MiniMap nodeColor={(n) => {
                const cat = (n.data as StrategyNodeData | undefined)?.category;
                return cat === "signal" ? "#8b5cf6" : cat === "risk" ? "#f59e0b" : cat === "logic" ? "#eab308" : cat === "indicator" ? "#22c55e" : "#3b82f6";
              }} maskColor="oklch(0.145 0.005 270 / 70%)" />
            </ReactFlow>
            {nodes.length === 0 && (
              <div className="pointer-events-none absolute inset-0 grid place-items-center">
                <div className="pointer-events-auto max-w-md rounded-xl border border-dashed border-border bg-elevated/80 p-6 text-center backdrop-blur">
                  <div className="mb-2 text-sm font-semibold">Build your strategy in 5 steps</div>
                  <ol className="mb-4 space-y-1 text-left text-xs text-muted-foreground">
                    <li><span className="text-stocks">1.</span> Add a <b className="text-foreground">Data</b> source from the left palette</li>
                    <li><span className="text-futures">2.</span> Add an <b className="text-foreground">Indicator</b> and drag from its right dot to the data node</li>
                    <li><span className="text-gold">3.</span> Add a <b className="text-foreground">Logic</b> node to compare values</li>
                    <li><span className="text-crypto">4.</span> Add <b className="text-foreground">Risk</b> rules (stop, target, size)</li>
                    <li><span className="text-violet">5.</span> Connect into an <b className="text-foreground">Entry Signal</b> — then Run Backtest</li>
                  </ol>
                  <Button size="sm" onClick={() => setShowTemplates(true)} className="bg-violet text-violet-foreground hover:bg-violet/90">
                    <FileCode className="mr-1 size-4" /> Start from a template
                  </Button>
                </div>
              </div>
            )}
          </div>


          {/* Console */}
          <div className="border-t border-border bg-elevated">
            <button onClick={() => setConsoleOpen((o) => !o)} className="flex w-full items-center justify-between px-3 py-1.5 text-xs font-mono uppercase tracking-wider text-muted-foreground hover:bg-muted/30">
              <span>Output Console · {logs.length} entries</span>
              {consoleOpen ? <ChevronDown className="size-3" /> : <ChevronUp className="size-3" />}
            </button>
            {consoleOpen && (
              <div className="max-h-40 overflow-y-auto border-t border-border bg-background/40 px-3 py-2 font-mono text-[11px] leading-relaxed">
                {logs.map((l, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="text-muted-foreground">{new Date(l.ts).toLocaleTimeString()}</span>
                    {l.level === "error" && <AlertCircle className="mt-0.5 size-3 text-danger" />}
                    {l.level === "ok" && <CheckCircle2 className="mt-0.5 size-3 text-futures" />}
                    <span className={l.level === "error" ? "text-danger" : l.level === "ok" ? "text-futures" : "text-foreground"}>{l.msg}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>


        {/* Inspector */}
        <div className="w-72 shrink-0 border-l border-border bg-sidebar">
          <NodeInspector node={selectedNode} onChange={updateNodeConfig} onDelete={deleteNode} />
        </div>
      </div>


      {/* Template picker */}
      <Dialog open={showTemplates} onOpenChange={setShowTemplates}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Start from a template</DialogTitle>
            <DialogDescription>Each template is a working strategy you can modify, backtest, and deploy.</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {(templates ?? []).map((t) => (
              <Card key={t.id} className="cursor-pointer border-border bg-background p-4 hover:border-violet/40" onClick={() => loadTemplate(t.id)}>
                <div className="text-sm font-medium">{t.name}</div>
                <div className="mt-1 text-xs text-muted-foreground">{t.description}</div>
                <div className="mt-2 font-mono text-[10px] uppercase tracking-wider text-violet">{t.assetClass}</div>
              </Card>
            ))}
            <Card className="cursor-pointer border-dashed border-border bg-background p-4 hover:border-violet/40" onClick={() => { setShowTemplates(false); setNodes([]); setEdges([]); }}>
              <div className="text-sm font-medium">Start from scratch</div>
              <div className="mt-1 text-xs text-muted-foreground">Blank canvas — build your strategy node by node.</div>
            </Card>
          </div>
        </DialogContent>
      </Dialog>

      <BacktestRunModal open={showBacktest} onOpenChange={setShowBacktest} onRun={async (p) => {
        const run = await handleRunBacktest(p);
        navigate({ to: "/studio/backtests/$strategyId", params: { strategyId: run.strategyId }, search: { runId: run.id } as never });
      }} />
    </div>
  );
}
