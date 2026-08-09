import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, RotateCcw, GitBranch, BarChart3, ShieldCheck, Check, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { CopilotChat } from "@/components/copilot/CopilotChat";
import { PipelineStepper } from "@/components/copilot/PipelineStepper";
import { GraphView } from "@/components/copilot/GraphView";
import { BacktestView } from "@/components/copilot/BacktestView";
import {
  getCopilotState, isWorking,
  type CopilotChatResponse, type CopilotState,
} from "@/lib/api/copilot";
import { getDevStrategies } from "@/lib/api/studio";

export const Route = createFileRoute("/studio/copilot")({
  head: () => ({ meta: [{ title: "Copilot — Bayn Studio" }] }),
  component: CopilotWorkspace,
});

type View = "graph" | "backtest" | "validation";

// Which workspace view a turn's tool calls should bring to the front.
function focusForTools(tools: { name: string }[]): View | null {
  const names = new Set(tools.map((t) => t.name));
  if (names.has("run_backtest") || names.has("get_backtest_analysis")) return "backtest";
  if (names.has("run_oos_test")) return "validation";
  if (names.has("build_strategy") || names.has("edit_strategy_node")) return "graph";
  return null;
}

function CopilotWorkspace() {
  const qc = useQueryClient();
  const [strategyId, setStrategyId] = useState<string | null>(null);
  const [state, setState] = useState<CopilotState | null>(null);
  const [view, setView] = useState<View>("graph");
  const [sessionKey, setSessionKey] = useState(0);

  const { data: strategies } = useQuery({
    queryKey: ["devStrategies"],
    queryFn: getDevStrategies,
  });

  // Poll lifecycle state while a run is in flight so the stepper/views update.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (strategyId && isWorking(state)) {
      pollRef.current = setInterval(async () => {
        try {
          setState(await getCopilotState(strategyId));
          qc.invalidateQueries({ queryKey: ["bt"] });
        } catch { /* transient */ }
      }, 4000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [strategyId, state, qc]);

  const onResult = useCallback((res: CopilotChatResponse) => {
    if (res.strategy_id) setStrategyId(res.strategy_id);
    if (res.state) setState(res.state);
    const next = focusForTools(res.tool_trace ?? []);
    if (next) setView(next);
    // Tool calls may have changed the graph or produced a new backtest.
    qc.invalidateQueries({ queryKey: ["devStrategy"] });
    qc.invalidateQueries({ queryKey: ["devStrategies"] });
    qc.invalidateQueries({ queryKey: ["bt"] });
  }, [qc]);

  const loadStrategy = useCallback(async (id: string) => {
    setStrategyId(id);
    setSessionKey((k) => k + 1);
    setView("graph");
    try { setState(await getCopilotState(id)); } catch { setState(null); }
  }, []);

  const startFresh = useCallback(() => {
    setStrategyId(null);
    setState(null);
    setView("graph");
    setSessionKey((k) => k + 1);
  }, []);

  const TABS: { key: View; label: string; icon: typeof GitBranch }[] = [
    { key: "graph", label: "Nodes", icon: GitBranch },
    { key: "backtest", label: "Backtest", icon: BarChart3 },
    { key: "validation", label: "Validation", icon: ShieldCheck },
  ];

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* Left rail — the copilot */}
      <aside className="flex w-[380px] shrink-0 flex-col border-r border-border bg-sidebar">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
          <div className="grid size-7 place-items-center rounded-lg bg-violet/15 text-violet">
            <Sparkles className="size-4" />
          </div>
          <span className="text-sm font-semibold tracking-tight">Copilot</span>
          <div className="ml-auto flex items-center gap-1.5">
            <Select
              value={strategyId ?? "new"}
              onValueChange={(v) => (v === "new" ? startFresh() : loadStrategy(v))}
            >
              <SelectTrigger className="h-8 w-40 border-border bg-elevated text-xs">
                <SelectValue placeholder="New strategy" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="new">+ New strategy</SelectItem>
                {strategies?.map((s) => (
                  <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="ghost" size="icon" className="size-8" onClick={startFresh} title="Start over" aria-label="Start over">
              <RotateCcw className="size-3.5" />
            </Button>
          </div>
        </div>
        <div className="min-h-0 flex-1 px-3 pb-3 pt-1">
          <CopilotChat
            key={sessionKey}
            strategyId={strategyId}
            suggestedAction={state?.next_action ?? null}
            onResult={onResult}
          />
        </div>
      </aside>

      {/* Main — contextual workspace */}
      <main className="flex min-w-0 flex-1 flex-col">
        {/* Stepper + view tabs */}
        <div className="border-b border-border bg-elevated/40 px-4 py-3">
          {state ? (
            <PipelineStepper state={state} />
          ) : (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Sparkles className="size-4 text-violet" />
              Describe a strategy in the copilot to get started — it'll appear here as you build.
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 border-b border-border px-3 py-1.5">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = view === t.key;
            return (
              <button
                key={t.key}
                onClick={() => setView(t.key)}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                  active ? "bg-violet/15 text-violet" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="size-3.5" /> {t.label}
              </button>
            );
          })}
        </div>

        {/* Active view */}
        <div className="min-h-0 flex-1 overflow-hidden">
          {!strategyId ? (
            <div className="grid h-full place-items-center px-6 text-center text-sm text-muted-foreground">
              Nothing here yet — your strategy, backtest, and validation results will show up here
              as the copilot works.
            </div>
          ) : view === "graph" ? (
            <GraphView strategyId={strategyId} />
          ) : view === "backtest" ? (
            <div className="h-full overflow-y-auto p-3">
              <BacktestView
                backtestId={state?.latest_backtest_id ?? null}
                status={state?.latest_backtest_status}
              />
            </div>
          ) : (
            <div className="h-full overflow-y-auto p-4">
              <ValidationView state={state} />
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function ValidationView({ state }: { state: CopilotState | null }) {
  if (!state || !state.latest_oos_id) {
    return (
      <div className="grid h-full place-items-center px-6 text-center text-sm text-muted-foreground">
        No out-of-sample test yet. Once your backtest looks good, ask the copilot to
        "run the out-of-sample test".
      </div>
    );
  }
  const running = state.latest_oos_status === "pending" || state.latest_oos_status === "running";
  const passed = state.gates_passed.oos_passed;
  return (
    <div className="mx-auto max-w-xl space-y-4">
      <Card className="border-border bg-elevated p-5">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "grid size-10 place-items-center rounded-xl",
              running ? "bg-muted text-muted-foreground" : passed ? "bg-ok/15 text-ok" : "bg-danger/15 text-danger",
            )}
          >
            {running ? <ShieldCheck className="size-5" /> : passed ? <Check className="size-5" /> : <X className="size-5" />}
          </div>
          <div>
            <div className="text-base font-semibold">
              {running ? "Out-of-sample test running…" : passed ? "Held up out of sample" : "Didn't hold up out of sample"}
            </div>
            <div className="text-sm text-muted-foreground">
              {running
                ? "Re-testing on held-out history the strategy was never tuned on."
                : "Walk-forward across windows the strategy never saw during tuning."}
            </div>
          </div>
        </div>
        {!running && (
          <div className="mt-4 grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-border bg-background/50 px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">OOS Sharpe</div>
              <div className={cn("mt-0.5 font-mono text-lg", passed ? "text-ok" : "text-danger")}>
                {state.avg_test_sharpe !== null ? state.avg_test_sharpe.toFixed(2) : "—"}
              </div>
            </div>
            <div className="rounded-lg border border-border bg-background/50 px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Verdict</div>
              <div className={cn("mt-0.5 text-sm font-semibold", passed ? "text-ok" : "text-danger")}>
                {passed ? "Passed" : "Failed"}
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
