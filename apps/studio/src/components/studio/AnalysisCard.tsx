import { useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import {
  Brain, Sparkles, TrendingUp, TrendingDown, AlertTriangle, Info,
  CheckCircle2, Wrench, Loader2, SlidersHorizontal, RotateCw,
} from "lucide-react";
import { toast } from "sonner";
import { generateBacktestNarrative, suggestBacktestTweaks } from "@/lib/api/studio";
import type {
  BacktestAnalysis, AnalysisFinding, AnalysisSeverity, ParamTweak, StrategyGraph,
} from "@/lib/types";

const VERDICT_META: Record<
  BacktestAnalysis["verdict"],
  { label: string; cls: string; ring: string }
> = {
  profitable:   { label: "Profitable",   cls: "text-success", ring: "border-success/40 bg-success/10" },
  marginal:     { label: "Marginal",     cls: "text-amber-400", ring: "border-amber-400/40 bg-amber-400/10" },
  unprofitable: { label: "Unprofitable", cls: "text-danger",  ring: "border-danger/40 bg-danger/10" },
  inconclusive: { label: "Inconclusive", cls: "text-muted-foreground", ring: "border-border bg-muted/20" },
};

const SEV_META: Record<AnalysisSeverity, { icon: typeof Info; cls: string; chip: string }> = {
  good: { icon: CheckCircle2,   cls: "text-success", chip: "border-success/30 bg-success/5" },
  warn: { icon: AlertTriangle,  cls: "text-amber-400", chip: "border-amber-400/30 bg-amber-400/5" },
  bad:  { icon: TrendingDown,   cls: "text-danger",  chip: "border-danger/30 bg-danger/5" },
  info: { icon: Info,           cls: "text-muted-foreground", chip: "border-border bg-muted/10" },
};

function ScoreRing({ score }: { score: number }) {
  const hue = score >= 66 ? "var(--success)" : score >= 40 ? "#fbbf24" : "var(--danger)";
  return (
    <div className="relative grid size-16 shrink-0 place-items-center">
      <svg viewBox="0 0 36 36" className="size-16 -rotate-90">
        <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--border)" strokeWidth="3" />
        <circle
          cx="18" cy="18" r="15.5" fill="none" stroke={hue} strokeWidth="3"
          strokeLinecap="round" strokeDasharray={`${(score / 100) * 97.4} 97.4`}
        />
      </svg>
      <div className="absolute text-center">
        <div className="font-mono text-lg leading-none">{score}</div>
        <div className="text-[8px] uppercase tracking-wider text-muted-foreground">score</div>
      </div>
    </div>
  );
}

function FindingRow({ f }: { f: AnalysisFinding }) {
  const meta = SEV_META[f.severity] ?? SEV_META.info;
  const Icon = meta.icon;
  return (
    <div className={cn("rounded-md border p-3", meta.chip)}>
      <div className="flex items-start gap-2">
        <Icon className={cn("mt-0.5 size-4 shrink-0", meta.cls)} />
        <div className="min-w-0 flex-1">
          <div className={cn("text-sm font-medium", meta.cls)}>{f.title}</div>
          <p className="mt-0.5 text-sm text-muted-foreground">{f.detail}</p>
          {f.suggestion && (
            <div className="mt-1.5 flex items-start gap-1.5 text-xs text-foreground/80">
              <Wrench className="mt-0.5 size-3 shrink-0 text-violet" />
              <span>{f.suggestion}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const fmt = (n: number | null | undefined, dp = 2, suffix = "") =>
  n == null ? "—" : `${n.toFixed(dp)}${suffix}`;

export function AnalysisCard({
  analysis, backtestId, graph, onApplyTweaks,
}: {
  analysis: BacktestAnalysis;
  backtestId: string;
  // The strategy's current builder graph — present for graph-built strategies,
  // enabling the AI param-tweak loop. Absent (e.g. built-in code strategies)
  // hides the tweak panel.
  graph?: StrategyGraph | null;
  // Patch the graph with the chosen tweaks, then re-backtest. Provided by the
  // page (it owns runBacktest + navigation).
  onApplyTweaks?: (patched: StrategyGraph) => Promise<void>;
}) {
  const verdict = VERDICT_META[analysis.verdict] ?? VERDICT_META.inconclusive;
  const m = analysis.metrics ?? ({} as BacktestAnalysis["metrics"]);
  const [narrative, setNarrative] = useState<string | null>(analysis.narrative ?? null);
  const [loading, setLoading] = useState(false);

  const canTune = !!(graph && graph.nodes?.length && onApplyTweaks);

  const grouped = useMemo(() => {
    const order: AnalysisSeverity[] = ["bad", "warn", "good", "info"];
    return [...(analysis.findings ?? [])].sort(
      (a, b) => order.indexOf(a.severity) - order.indexOf(b.severity),
    );
  }, [analysis.findings]);

  async function explain() {
    setLoading(true);
    try {
      const res = await generateBacktestNarrative(backtestId);
      if (res.ok && res.narrative) {
        setNarrative(res.narrative);
        toast.success("AI narrative generated");
      } else {
        toast.error(res.error ?? "Couldn't generate the narrative.");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Narrative request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="border-violet/30 bg-elevated p-4">
      {/* Header: verdict + score + headline */}
      <div className="flex flex-wrap items-center gap-4">
        <ScoreRing score={analysis.score} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Brain className="size-4 text-violet" />
            <span className="text-sm font-semibold">AI analysis</span>
            <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", verdict.ring, verdict.cls)}>
              {verdict.label}
            </span>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{analysis.headline}</p>
        </div>
        <Button size="sm" variant="outline" onClick={explain} disabled={loading} className="gap-1.5">
          {loading ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5 text-violet" />}
          {narrative ? "Regenerate" : "Explain with AI"}
        </Button>
      </div>

      {/* Key derived metrics */}
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {[
          ["Profit factor", fmt(m.profit_factor)],
          ["Sharpe", fmt(m.sharpe)],
          ["Win rate", fmt(m.win_rate_pct, 0, "%")],
          ["Breakeven", fmt(m.breakeven_win_pct, 0, "%")],
          ["Payoff", fmt(m.payoff_ratio, 2, ":1")],
          ["Expectancy", fmt(m.expectancy_pct, 2, "%")],
        ].map(([k, v]) => (
          <div key={k} className="rounded-md border border-border bg-background/40 p-2">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{k}</div>
            <div className="mt-0.5 font-mono text-sm">{v}</div>
          </div>
        ))}
      </div>

      {/* LLM narrative (once generated) */}
      {narrative && (
        <div className="mt-3 rounded-md border border-violet/20 bg-violet/5 p-3">
          <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-violet">
            <Sparkles className="size-3" /> Narrative
          </div>
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">{narrative}</div>
        </div>
      )}

      {/* Findings */}
      <div className="mt-3 space-y-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <TrendingUp className="size-3.5" /> What worked, what to fix · {grouped.length} findings
        </div>
        {grouped.length === 0 ? (
          <p className="text-sm text-muted-foreground">No findings — the run produced no closed trades to analyze.</p>
        ) : (
          grouped.map((f) => <FindingRow key={f.id} f={f} />)
        )}
      </div>

      {/* AI parameter tuning — suggest specific node tweaks, edit, re-backtest. */}
      {canTune && (
        <TweakPanel backtestId={backtestId} graph={graph!} onApply={onApplyTweaks!} />
      )}
    </Card>
  );
}

/** A single editable tweak row: which node/field, current value, an editable
 *  suggested value, and a checkbox to include it in the re-backtest. */
function asTyped(original: string | number | boolean | null, raw: string): string | number | boolean {
  if (typeof original === "number") {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  if (typeof original === "boolean") return raw === "true";
  return raw;
}

function TweakPanel({
  backtestId, graph, onApply,
}: {
  backtestId: string;
  graph: StrategyGraph;
  onApply: (patched: StrategyGraph) => Promise<void>;
}) {
  type Row = ParamTweak & { include: boolean; value: string };
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);

  async function fetchTweaks() {
    setLoading(true);
    try {
      const res = await suggestBacktestTweaks(backtestId, graph);
      if (!res.ok) {
        toast.error(res.error ?? "Couldn't get tweak suggestions.");
        return;
      }
      setSummary(res.summary || null);
      setRows(
        res.tweaks.map((t) => ({ ...t, include: true, value: String(t.suggested) })),
      );
      if (!res.tweaks.length) toast.info("No high-confidence parameter changes suggested.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Tweak request failed");
    } finally {
      setLoading(false);
    }
  }

  async function applyAndRerun() {
    if (!rows) return;
    const chosen = rows.filter((r) => r.include);
    if (!chosen.length) {
      toast.error("Select at least one tweak to apply.");
      return;
    }
    // Deep-clone the graph and patch each chosen node's field with the edited value.
    const patched: StrategyGraph = JSON.parse(JSON.stringify(graph));
    const byId = new Map(patched.nodes.map((n) => [n.id, n]));
    for (const r of chosen) {
      const node = byId.get(r.node_id);
      if (!node) continue;
      node.data = { ...(node.data ?? {}), [r.field]: asTyped(r.current, r.value) };
    }
    setApplying(true);
    try {
      await onApply(patched);
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="mt-4 rounded-md border border-violet/20 bg-violet/5 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-violet">
          <SlidersHorizontal className="size-3.5" /> AI parameter tuning
        </div>
        {!rows && (
          <Button size="sm" variant="outline" onClick={fetchTweaks} disabled={loading} className="gap-1.5">
            {loading ? <Loader2 className="size-3.5 animate-spin" /> : <Wrench className="size-3.5 text-violet" />}
            Suggest parameter tweaks
          </Button>
        )}
      </div>

      {!rows && (
        <p className="mt-1.5 text-xs text-muted-foreground">
          Let the AI find which strategy parameters to change based on this backtest, edit them, and re-run.
        </p>
      )}

      {rows && (
        <>
          {summary && <p className="mt-1.5 text-xs text-foreground/80">{summary}</p>}
          {rows.length === 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">No parameter changes suggested — the strategy looks reasonably tuned.</p>
          ) : (
            <div className="mt-2 space-y-2">
              {rows.map((r, i) => (
                <div key={`${r.node_id}-${r.field}`} className="rounded-md border border-border bg-background/50 p-2">
                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={r.include}
                      onCheckedChange={(v) =>
                        setRows((rs) => rs!.map((x, j) => (j === i ? { ...x, include: !!v } : x)))
                      }
                    />
                    <span className="flex-1 text-xs font-medium">
                      {r.node_label || r.node_type || r.node_id}
                      <span className="ml-1 font-mono text-[10px] text-muted-foreground">· {r.field}</span>
                    </span>
                    <span className="font-mono text-[11px] text-muted-foreground line-through">{String(r.current)}</span>
                    <span className="text-muted-foreground">→</span>
                    <Input
                      className="h-7 w-24 bg-background font-mono text-[11px]"
                      value={r.value}
                      onChange={(e) =>
                        setRows((rs) => rs!.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))
                      }
                    />
                  </div>
                  {r.rationale && <p className="mt-1 pl-6 text-[11px] text-muted-foreground">{r.rationale}</p>}
                </div>
              ))}
              <div className="flex items-center justify-end gap-2 pt-1">
                <Button size="sm" variant="ghost" onClick={fetchTweaks} disabled={loading || applying} className="gap-1.5">
                  {loading ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCw className="size-3.5" />} Re-suggest
                </Button>
                <Button
                  size="sm"
                  onClick={applyAndRerun}
                  disabled={applying || loading}
                  className="gap-1.5 bg-violet text-violet-foreground hover:bg-violet/90"
                >
                  {applying ? <Loader2 className="size-3.5 animate-spin" /> : <PlayIcon />}
                  Apply &amp; re-backtest
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function PlayIcon() {
  return <TrendingUp className="size-3.5" />;
}
