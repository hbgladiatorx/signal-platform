import { createFileRoute, Link, useParams, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { zodValidator, fallback } from "@tanstack/zod-adapter";
import { z } from "zod";
import { getBacktestsForStrategy, getBacktest, getDevStrategy, submitStrategyToBayn, deployStrategyLive, runBacktest, saveStrategyGraph, certifyBacktest, getCertReportHtml, skipForwardTest, type CertResult } from "@/lib/api/studio";
import type { StrategyGraph } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell,
  Line, LineChart,
} from "recharts";
import { ArrowLeft, Rocket, Send, CheckCircle2, ArrowRight, Activity, Sparkles, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { advanceStage, getStage, nextStage, STAGE_ORDER } from "@/lib/strategy-stage";
import { deployStageMeta, type DeployStage } from "@/lib/api/agent";
import type { BacktestRun } from "@/lib/types";
import { AnalysisCard } from "@/components/studio/AnalysisCard";
import { AttributionCard } from "@/components/studio/AttributionCard";
import { ModelCard } from "@/components/studio/ModelCard";
import { CardErrorBoundary } from "@/components/common/CardErrorBoundary";
import {
  AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogFooter,
  AlertDialogTitle, AlertDialogDescription, AlertDialogAction, AlertDialogCancel,
} from "@/components/ui/alert-dialog";

// Minimum closed trades for an out-of-sample result to be statistically
// meaningful — mirrors the backend's MIN_TRADES_CONFIDENT (backtest_analysis.py).
// Below this the verdict is "inconclusive": metrics like Sharpe/win-rate can't be
// trusted (a single lucky trade reads as a 100% win rate), so we don't silently
// pass — we route the user through an explicit "continue anyway?" gate.
const MIN_OOS_TRADES = 30;

const searchSchema = z.object({
  runId: fallback(z.string().optional(), undefined),
});

export const Route = createFileRoute("/studio/backtests/$strategyId")({
  head: () => ({ meta: [{ title: "Backtest results — Bayn Studio" }] }),
  validateSearch: zodValidator(searchSchema),
  component: BacktestDetail,
  errorComponent: BacktestDetailError,
});

// Route-level fallback: instead of a blank "this page didn't load", show the
// actual error so a render failure is diagnosable and recoverable.
function BacktestDetailError({ error }: { error: Error }) {
  return (
    <div className="p-6">
      <Card className="border-danger/30 bg-elevated p-5">
        <div className="flex items-start gap-3">
          <Activity className="mt-0.5 size-5 shrink-0 text-danger" />
          <div className="min-w-0">
            <h2 className="text-lg font-semibold">Couldn’t render this backtest</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Something went wrong displaying the results. The backtest data itself is safe.
            </p>
            <pre className="mt-3 max-h-48 overflow-auto rounded-md border border-border bg-background/60 p-3 text-xs text-danger">
              {error?.message || String(error)}
            </pre>
            <div className="mt-3 flex gap-2">
              <Button size="sm" variant="outline" onClick={() => window.location.reload()}>Reload</Button>
              <Button asChild size="sm" variant="ghost"><Link to="/studio/backtests">Back to backtests</Link></Button>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}

const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`;

// Referee verdict vocabulary (same language as the walk-forward view).
const CERT_VERDICT_CLS: Record<string, string> = {
  DEPLOY: "text-success",
  HOLD_CONDITIONAL: "text-amber-400",
  REJECT: "text-danger",
  UNVERIFIABLE: "text-muted-foreground",
};

/**
 * Minimal "Certify this backtest" affordance: send the backtest to the live
 * referee engine (exposure-aware path engaged server-side) and render the signed
 * verdict + a link to the signed report. Trials are self-declared and shown.
 */
function CertifyBacktestCard({ backtestId }: { backtestId: string }) {
  const [trials, setTrials] = useState(1);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CertResult | null>(null);

  const onCertify = async () => {
    setBusy(true);
    toast.loading("Certifying backtest…", { id: "certify" });
    try {
      const r = await certifyBacktest(backtestId, Math.max(1, Math.floor(trials)));
      setResult(r);
      toast.success(`Signed verdict · ${r.verdict}`, { id: "certify" });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Certification failed", { id: "certify" });
    } finally {
      setBusy(false);
    }
  };

  const openReport = async () => {
    if (!result?.verification_id) return;
    try {
      const html = await getCertReportHtml(result.verification_id);
      const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      window.open(url, "_blank", "noopener");
    } catch {
      toast.error("Could not open the signed report");
    }
  };

  return (
    <Card className="border-border bg-elevated p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck className="size-4 text-violet" /> Certify this backtest
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted-foreground">
          Trials tried <span className="opacity-70">(self-declared)</span>
          <Input
            type="number"
            min={1}
            value={trials}
            onChange={(e) => setTrials(Number(e.target.value) || 1)}
            className="mt-1 w-28 bg-background"
          />
        </label>
        <Button size="sm" disabled={busy} onClick={onCertify}>
          {busy ? "Certifying…" : "Certify"}
        </Button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Grades this backtest's net returns through the Referee gauntlet and returns an
        Ed25519-signed verdict. The trial count you declare is fed into the deflation
        (stamped <span className="font-mono">self_declared</span>) — the same integrity bar as every path.
      </p>
      {result && (
        <div className="mt-3 rounded border border-border bg-background p-3 text-sm">
          <div>
            Verdict:{" "}
            <span className={cn("font-semibold", CERT_VERDICT_CLS[result.verdict] ?? "text-foreground")}>
              {result.verdict}
            </span>
            {result.insecure && <span className="ml-2 text-danger">⚠ insecure dev key — do not trust</span>}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            ID <span className="font-mono text-foreground">{result.verification_id}</span> · trials{" "}
            {result.n_trials_used} (declared {result.declared_trials}, self-declared)
          </div>
          {result.verification_id && (
            <Button size="sm" variant="outline" className="mt-2" onClick={openReport}>
              View signed report
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}

function BacktestDetail() {
  const { strategyId } = useParams({ from: "/studio/backtests/$strategyId" });
  const { runId } = Route.useSearch();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: runs } = useQuery({ queryKey: ["bts", strategyId], queryFn: () => getBacktestsForStrategy(strategyId) });
  const { data: strategy } = useQuery({ queryKey: ["devStrategy", strategyId], queryFn: () => getDevStrategy(strategyId) });

  const [selectedId, setSelectedId] = useState<string | undefined>(runId);
  useEffect(() => { if (runId) setSelectedId(runId); }, [runId]);

  // When OOS doesn't cleanly pass (negative return, or too few trades to judge)
  // we don't dead-end — we open this gate so the user can continue regardless.
  const [oosGate, setOosGate] = useState<
    null | { ret: number; nTrades: number; verdict?: string; inconclusive: boolean }
  >(null);

  const selectedRunId = selectedId ?? runId ?? runs?.[0]?.id;
  // The list gives light runs (stats only); fetch the selected run's full
  // detail (equity, trades, monthly returns) for the charts below.
  const { data: fullRun } = useQuery({
    queryKey: ["bt", selectedRunId],
    queryFn: () => getBacktest(selectedRunId!),
    enabled: !!selectedRunId,
  });
  const run = useMemo(
    () => fullRun ?? runs?.find((r) => r.id === selectedRunId) ?? runs?.[0],
    [fullRun, runs, selectedRunId],
  );

  // Stage tracking — viewing a backtest run implies the strategy is at least "backtested"
  const [stage, setStageState] = useState<DeployStage>(() => getStage(strategyId));
  // Recorded "skip forward testing" choice (honest opt-out, never a pass).
  const [fwdSkipped, setFwdSkipped] = useState(false);
  const onSkipForward = async () => {
    toast.loading("Recording skip & advancing to deployable…", { id: "skipfwd" });
    try {
      await skipForwardTest(strategyId);
      setFwdSkipped(true);
      advanceStage(strategyId, "deployable");
      toast.success("Forward testing skipped — advanced to deployable (recorded as skipped)", { id: "skipfwd" });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not skip forward testing", { id: "skipfwd" });
    }
  };
  useEffect(() => {
    const fn = () => setStageState(getStage(strategyId));
    window.addEventListener("bayn.stage.changed", fn);
    return () => window.removeEventListener("bayn.stage.changed", fn);
  }, [strategyId]);
  useEffect(() => {
    if (runs && runs.length > 0) advanceStage(strategyId, "backtested");
  }, [runs, strategyId]);


  if (!strategy) return <div className="p-6 text-muted-foreground">Loading…</div>;
  if (!run) return <div className="p-6 text-muted-foreground">No backtest runs yet.</div>;

  const stats = run.stats;
  const stepFns: Record<Exclude<DeployStage, "draft">, () => Promise<void>> = {
    backtested: async () => {
      // Out-of-sample = re-run the strategy on a *held-out recent window* it
      // wasn't evaluated on in-sample: the most recent ~30% of the time range
      // the backtest actually covered. We derive that range from the run's real
      // data timestamps (equity points + trade fills) rather than the params
      // dates — params dates are day-only, so an intraday (1m/5m) strategy that
      // ran inside a single day would collapse to a zero-length span and wrongly
      // trip "not enough history". The strategy "passes" OOS only if it stays
      // profitable on that unseen tail.
      const tsOf = (s: string) => +new Date(s);
      const stamps = [
        ...run.equity.map((e) => tsOf(e.t)),
        ...run.trades.flatMap((t) => [tsOf(t.entryDate), tsOf(t.exitDate)]),
        tsOf(run.params.startDate),
        tsOf(run.params.endDate),
      ].filter((n) => Number.isFinite(n) && n > 0);
      const lo = stamps.length ? Math.min(...stamps) : NaN;
      const hi = stamps.length ? Math.max(...stamps) : NaN;
      const span = hi - lo;
      if (!Number.isFinite(span) || span <= 0 || (run.stats.totalTrades ?? 0) === 0) {
        toast.error("Run a completed backtest with trades over a real time window first — there's nothing to hold out yet.");
        return;
      }
      // Hold out the most recent 30% of the covered window, as full ISO instants
      // (so intraday windows survive); the backend parses them as UTC.
      const oosStartIso = new Date(hi - Math.floor(span * 0.3)).toISOString();
      const oosEndIso = new Date(hi).toISOString();
      const oosStart = oosStartIso.slice(0, 10);
      const oosEnd = oosEndIso.slice(0, 10);
      toast.loading(`Running out-of-sample test (${oosStart} → ${oosEnd})…`, { id: "oos" });
      try {
        const r = await runBacktest(strategyId, {
          ...run.params,
          symbols: run.symbols && run.symbols.length ? run.symbols : undefined,
          barResolution: run.barResolution,
          windowStart: oosStartIso,
          windowEnd: oosEndIso,
        });
        const ret = r.stats.totalReturn;
        const nTrades = r.stats.totalTrades ?? 0;
        const verdict = r.analysis?.verdict;
        // Too few trades to judge → inconclusive, even if the return is positive
        // (a single lucky trade would otherwise sail through as a "pass").
        const inconclusive = nTrades < MIN_OOS_TRADES || verdict === "inconclusive";
        const profitable = Number.isFinite(ret) && ret > 0;
        await qc.invalidateQueries({ queryKey: ["bts", strategyId] });
        navigate({ to: "/studio/backtests/$strategyId", params: { strategyId }, search: { runId: r.id } as never });

        if (profitable && !inconclusive) {
          advanceStage(strategyId, "oos");
          toast.success(`OOS passed · ${fmtPct(ret)} on held-out data · ${nTrades} trades`, { id: "oos" });
        } else {
          // Don't dead-end. Surface why, and let the user continue regardless.
          toast.dismiss("oos");
          setOosGate({ ret, nTrades, verdict, inconclusive });
        }
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Out-of-sample test failed to run", { id: "oos" });
      }
    },
    oos: async () => {
      // Forward test = a REAL cross-platform PAPER session (simulated funds,
      // Alpaca paper). No real money. Real-money live is the separate, opt-in
      // "forward" step below.
      toast.loading("Starting paper forward test…", { id: "fwd" });
      try {
        await deployStrategyLive(strategyId, { mode: "paper" });
        advanceStage(strategyId, "forward");
        toast.success("Paper forward test running — live cross-platform signals, no real money", { id: "fwd" });
        navigate({ to: "/studio/live" });
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Could not start forward test", { id: "fwd" });
      }
    },
    forward: async () => {
      // Going live places REAL-money orders on the connected broker
      // (Binance.US crypto / Alpaca live equities). Gate behind explicit opt-in.
      const ok = window.confirm(
        "Go live with REAL money?\n\nThis routes orders to your connected broker (Binance.US / Alpaca live) and uses real funds. Only continue if you've reviewed the paper forward-test results.",
      );
      if (!ok) return;
      try {
        await deployStrategyLive(strategyId, { mode: "live" });
        advanceStage(strategyId, "deployable");
        toast.success("Strategy is live with real money in your personal signals");
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Could not deploy strategy");
      }
    },
    deployable: async () => {
      advanceStage(strategyId, "eligible");
      await submitStrategyToBayn(strategyId);
      toast.success("Submitted to the Bayn catalog for review");
    },
    eligible: async () => {
      toast.info("Already eligible for the Bayn catalog");
    },
  };
  const next = nextStage(stage);

  return (
    <div className="space-y-5 p-4 md:p-6">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild variant="ghost" size="sm"><Link to="/studio/backtests"><ArrowLeft className="mr-1 size-4" /> Backtests</Link></Button>
        <div className="flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">{strategy.name}</h1>
          <p className="text-sm text-muted-foreground">Backtest <span className="font-mono text-foreground">{run.id.slice(-8)}</span> · {new Date(run.ranAt).toLocaleString()}</p>
        </div>
        <Select value={run.id} onValueChange={(v) => navigate({ to: "/studio/backtests/$strategyId", params: { strategyId }, search: { runId: v } as never })}>
          <SelectTrigger className="w-64 bg-elevated"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(runs ?? []).map((r) => <SelectItem key={r.id} value={r.id}>Run · {new Date(r.ranAt).toLocaleString()}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {/* Validation pipeline stepper */}
      <Card className="border-violet/20 bg-elevated p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Activity className="size-4 text-violet" /> Validation pipeline
          </div>
          <div className="flex items-center gap-2">
            {/* Explicit opt-out at the OOS stage: forward testing is still the
                default (primary button); skip is a recorded, secondary choice. */}
            {stage === "oos" && !fwdSkipped && (
              <Button size="sm" variant="ghost" className="text-muted-foreground"
                title="Advance toward deployable without forward testing (recorded as skipped)"
                onClick={onSkipForward}>
                Skip forward testing
              </Button>
            )}
            {next && (
              <Button size="sm" className="bg-violet text-violet-foreground hover:bg-violet/90"
                onClick={() => stepFns[stage as Exclude<DeployStage, "draft">]?.()}>
                {nextStepLabel(stage)} <ArrowRight className="ml-1 size-3.5" />
              </Button>
            )}
          </div>
        </div>
        {fwdSkipped && (
          <div className="mb-2 inline-flex items-center gap-1.5 rounded border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-xs text-amber-400">
            <Activity className="size-3.5" /> Forward test: skipped — advanced to deployable without forward-test evidence
          </div>
        )}
        <Stepper current={stage} />
      </Card>

      {/* Certify this backtest — door into the live referee engine */}
      <CertifyBacktestCard backtestId={run.id} />

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        {[
          ["Total Return", fmtPct(stats.totalReturn)],
          ["CAGR", fmtPct(stats.cagr)],
          ["Sharpe", stats.sharpe.toFixed(2)],
          ["Sortino", stats.sortino.toFixed(2)],
          ["Max DD", fmtPct(stats.maxDrawdown)],
          ["Win Rate", `${(stats.winRate * 100).toFixed(0)}%`],
          ["Profit Factor", stats.profitFactor.toFixed(2)],
          ["Avg Win", `${stats.avgWin.toFixed(2)}R`],
          ["Avg Loss", `${stats.avgLoss.toFixed(2)}R`],
          ["Avg Hold", `${stats.avgHoldDays}d`],
          ["Total Trades", String(stats.totalTrades)],
          ["Capital", `$${run.params.capital.toLocaleString()}`],
        ].map(([k, v]) => (
          <Card key={k} className="border-border bg-elevated p-3">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{k}</div>
            <div className="mt-1 font-mono text-lg">{v}</div>
          </Card>
        ))}
      </div>

      {/* AI analysis — the "what worked / why / what to fix" + param tuning */}
      {run.analysis && (
        <CardErrorBoundary label="AI analysis">
          <AnalysisCard
            analysis={run.analysis}
            backtestId={run.id}
            graph={strategy.graph?.nodes?.length ? strategy.graph : null}
            onApplyTweaks={async (patched: StrategyGraph) => {
              toast.loading("Applying tweaks & re-backtesting…", { id: "tweak" });
              try {
                // Persist the patched graph (re-translates the changed nodes to
                // runnable code), then re-run on the same instruments + window.
                await saveStrategyGraph(strategyId, patched);
                const r = await runBacktest(strategyId, {
                  ...run.params,
                  symbols: run.symbols && run.symbols.length ? run.symbols : undefined,
                  barResolution: run.barResolution,
                });
                toast.success(`Re-backtest done · ${fmtPct(r.stats.totalReturn)}`, { id: "tweak" });
                await qc.invalidateQueries({ queryKey: ["bts", strategyId] });
                await qc.invalidateQueries({ queryKey: ["devStrategy", strategyId] });
                navigate({ to: "/studio/backtests/$strategyId", params: { strategyId }, search: { runId: r.id } as never });
              } catch (e) {
                toast.error(e instanceof Error ? e.message : "Re-backtest failed", { id: "tweak" });
                throw e;
              }
            }}
          />
        </CardErrorBoundary>
      )}

      {/* Equity */}
      <Card className="border-border bg-elevated p-4">
        <div className="mb-2 text-sm font-medium">Equity curve</div>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={run.equity}>
              <defs><linearGradient id="eqg2" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--violet)" stopOpacity={0.4} /><stop offset="100%" stopColor="var(--violet)" stopOpacity={0} /></linearGradient></defs>
              <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
              <XAxis dataKey="t" tickFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: "short" })} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
              <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
              <Area type="monotone" dataKey="equity" stroke="var(--violet)" strokeWidth={2} fill="url(#eqg2)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* Attribution + ML model — per-symbol / per-signal "why" */}
      {run.attribution && (
        <CardErrorBoundary label="attribution">
          <AttributionCard attribution={run.attribution} />
        </CardErrorBoundary>
      )}
      {run.mlModel && (
        <CardErrorBoundary label="signal-edge model">
          <ModelCard model={run.mlModel} />
        </CardErrorBoundary>
      )}

      {/* Drawdown curve */}
      <DrawdownCard run={run} />

      {/* Monte Carlo */}
      <MonteCarloCard run={run} />

      {/* Distributions */}
      <div className="grid gap-3 lg:grid-cols-2">
        <RDistributionCard run={run} />
        <TerminalValueCard run={run} />
      </div>


      {/* Monthly heatmap-ish */}
      <Card className="border-border bg-elevated p-4">
        <div className="mb-2 text-sm font-medium">Monthly returns</div>
        <div className="h-40">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={run.monthlyReturns}>
              <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
              <XAxis dataKey="month" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
              <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => fmtPct(v)} />
              <Bar dataKey="ret">
                {run.monthlyReturns.map((d, i) => (
                  <Cell key={i} fill={d.ret >= 0 ? "var(--cyan)" : "var(--danger)"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* Trades table */}
      <Card className="border-border bg-elevated">
        <div className="border-b border-border p-4 text-sm font-medium">Trade-by-trade · {run.trades.length} trades</div>
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/20 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="p-2 text-left">Entry</th>
                <th className="p-2 text-left">Exit</th>
                <th className="p-2 text-left">Symbol</th>
                <th className="p-2 text-left">Side</th>
                <th className="p-2 text-right">Entry $</th>
                <th className="p-2 text-right">Exit $</th>
                <th className="p-2 text-right">P&L %</th>
                <th className="p-2 text-right">R</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border font-mono text-xs">
              {run.trades.slice(0, 80).map((t) => (
                <tr key={t.id}>
                  <td className="p-2">{new Date(t.entryDate).toLocaleDateString()}</td>
                  <td className="p-2">{new Date(t.exitDate).toLocaleDateString()}</td>
                  <td className="p-2">{t.symbol}</td>
                  <td className={cn("p-2", t.direction === "LONG" ? "text-cyan" : "text-danger")}>{t.direction}</td>
                  <td className="p-2 text-right">{t.entry.toFixed(2)}</td>
                  <td className="p-2 text-right">{t.exit.toFixed(2)}</td>
                  <td className={cn("p-2 text-right", t.pnlPct >= 0 ? "text-cyan" : "text-danger")}>{fmtPct(t.pnlPct)}</td>
                  <td className={cn("p-2 text-right", t.pnlR >= 0 ? "text-cyan" : "text-danger")}>{t.pnlR.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Footer actions */}
      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        <Button variant="outline" onClick={async () => {
          const ok = window.confirm(
            "Deploy LIVE with real money?\n\nThis routes orders to your connected broker (Binance.US / Alpaca live) using real funds. Run a paper forward test first if you haven't.",
          );
          if (!ok) return;
          try {
            await deployStrategyLive(strategyId, { mode: "live" });
            advanceStage(strategyId, "deployable");
            toast.success("Deployed live with real money");
          } catch (e) {
            toast.error(e instanceof Error ? e.message : "Could not deploy strategy");
          }
        }}>
          <Rocket className="mr-1 size-4" /> Deploy Live
        </Button>
        <Button className="bg-violet text-violet-foreground hover:bg-violet/90"
          onClick={async () => { await submitStrategyToBayn(strategyId); advanceStage(strategyId, "eligible"); toast.success("Submitted to Bayn for review"); }}>
          <Send className="mr-1 size-4" /> Submit to Bayn
        </Button>
      </div>

      {/* OOS gate — opens when the out-of-sample test didn't cleanly pass,
          so the user can review/tune or continue to the forward test anyway. */}
      <AlertDialog open={!!oosGate} onOpenChange={(open) => !open && setOosGate(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {oosGate?.inconclusive
                ? "Out-of-sample test was inconclusive"
                : "Strategy didn’t hold up out-of-sample"}
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3">
                {oosGate?.inconclusive ? (
                  <p>
                    Only <span className="font-mono text-foreground">{oosGate?.nTrades}</span>{" "}
                    trade{oosGate?.nTrades === 1 ? "" : "s"} cleared in the held-out window — too few
                    to tell whether the edge is real. With this little data, Sharpe and win rate
                    aren’t meaningful (a single lucky trade reads as a 100% win rate).
                  </p>
                ) : (
                  <p>
                    Held-out return was{" "}
                    <span className="font-mono text-danger">{oosGate ? fmtPct(oosGate.ret) : ""}</span>{" "}
                    across <span className="font-mono text-foreground">{oosGate?.nTrades}</span>{" "}
                    trade{oosGate?.nTrades === 1 ? "" : "s"}. The strategy lost money on data it
                    wasn’t tuned on.
                  </p>
                )}
                <p className="rounded-md border border-border bg-muted/20 p-3 text-xs">
                  To get a trustworthy result, loosen entry conditions, widen the date range, or use a
                  lower timeframe so the run generates at least{" "}
                  <span className="font-mono text-foreground">{MIN_OOS_TRADES}</span> trades — then
                  re-run the out-of-sample test. (Strategies run on one symbol, so adding symbols
                  isn’t an option.)
                </p>
                <p className="text-xs">
                  You can still continue to the forward test, but treat its results with caution
                  until the sample size is large enough to trust.
                </p>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Review &amp; tune</AlertDialogCancel>
            <AlertDialogAction
              className="bg-violet text-violet-foreground hover:bg-violet/90"
              onClick={() => {
                advanceStage(strategyId, "oos");
                setOosGate(null);
                toast.success("Continuing past out-of-sample — you can now deploy to the forward test.");
              }}
            >
              Continue anyway
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function nextStepLabel(stage: DeployStage): string {
  switch (stage) {
    case "draft":      return "Needs backtest";
    case "backtested": return "Continue to OOS test";
    case "oos":        return "Deploy to forward test";
    case "forward":    return "Go live (personal signals)";
    case "deployable": return "Submit to Bayn catalog";
    case "eligible":   return "Eligible";
  }
}

function Stepper({ current }: { current: DeployStage }) {
  const idx = STAGE_ORDER.indexOf(current);
  return (
    <ol className="flex flex-wrap items-center gap-1.5">
      {STAGE_ORDER.map((s, i) => {
        const meta = deployStageMeta(s);
        const done = i < idx;
        const active = i === idx;
        return (
          <li key={s} className="flex items-center gap-1.5">
            <div
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium",
                done && "border-success/40 bg-success/10 text-success",
                active && "border-violet/50 bg-violet/15 text-violet shadow-sm shadow-violet/20",
                !done && !active && "border-border bg-muted/20 text-muted-foreground",
              )}
            >
              {done ? <CheckCircle2 className="size-3" /> : <span>{meta.icon}</span>}
              <span>{meta.label}</span>
            </div>
            {i < STAGE_ORDER.length - 1 && <ArrowRight className="size-3 text-muted-foreground" />}
          </li>
        );
      })}
    </ol>
  );
}

function MonteCarloCard({ run }: { run: BacktestRun }) {
  const sims = useMemo(() => generateMonteCarlo(run), [run.id]);
  if (sims.degenerate) {
    return (
      <Card className="border-border bg-elevated p-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-medium">
          <Sparkles className="size-4 text-violet" /> Monte Carlo
        </div>
        <p className="text-sm text-muted-foreground">
          Needs at least one closed trade to resample. This run had none, so there's nothing to simulate.
        </p>
      </Card>
    );
  }
  return (
    <Card className="border-border bg-elevated p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Sparkles className="size-4 text-violet" /> Monte Carlo · {sims.paths.length} simulations
        </div>
        <div className="flex items-center gap-3 font-mono text-[11px] text-muted-foreground">
          <span>p5 <span className="text-foreground">{fmtPct(sims.p5)}</span></span>
          <span>median <span className="text-foreground">{fmtPct(sims.p50)}</span></span>
          <span>p95 <span className="text-foreground">{fmtPct(sims.p95)}</span></span>
          <span>Risk of ruin <span className={cn(sims.ruin > 0.05 ? "text-danger" : "text-success")}>{(sims.ruin * 100).toFixed(1)}%</span></span>
        </div>
      </div>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={sims.chart}>
            <CartesianGrid stroke="oklch(1 0 0 / 6%)" vertical={false} />
            <XAxis dataKey="i" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
            <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => `$${Math.round(v).toLocaleString()}`} />
            {sims.paths.map((_, k) => (
              <Line
                key={k}
                type="monotone"
                dataKey={`p${k}`}
                stroke={`hsl(${(k * 137.508) % 360} 85% 60%)`}
                strokeOpacity={0.55}
                strokeWidth={1}
                dot={false}
                isAnimationActive={false}
              />
            ))}
            <Line type="monotone" dataKey="median" stroke="var(--foreground)" strokeWidth={2.5} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="p5" stroke="var(--foreground)" strokeOpacity={0.7} strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="p95" stroke="var(--foreground)" strokeOpacity={0.7} strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function generateMonteCarlo(run: BacktestRun) {
  // Needs a positive starting capital and at least one closed trade to
  // resample. Without them the sim divides by zero → NaN percentiles and a
  // bogus 100% "risk of ruin". Flag it so the card shows a clear message.
  const cap = run.params.capital > 0 ? run.params.capital : (run.equity[0]?.equity ?? 0);
  if (cap <= 0 || run.trades.length === 0) {
    return { degenerate: true, chart: [] as Record<string, number>[], paths: [] as number[][], p5: 0, p50: 0, p95: 0, ruin: 0 };
  }
  const rets = run.trades.map((t) => t.pnlR * 0.01); // approximate per-trade return
  const N = 250;
  const T = Math.min(Math.max(rets.length, 40), 120);
  const paths: number[][] = [];
  for (let i = 0; i < N; i++) {
    const p: number[] = [run.params.capital];
    let v = run.params.capital;
    for (let t = 0; t < T; t++) {
      const r = rets.length ? rets[Math.floor(Math.random() * rets.length)] : 0;
      v = Math.max(v * (1 + r), 0);
      p.push(v);
    }
    paths.push(p);
  }
  // build chart rows — include every path so the spaghetti plot fans out like the reference
  const chart = Array.from({ length: T + 1 }).map((_, i) => {
    const row: Record<string, number> = { i };
    const col = paths.map((p) => p[i]).sort((a, b) => a - b);
    row.p5 = col[Math.floor(0.05 * N)];
    row.median = col[Math.floor(0.5 * N)];
    row.p95 = col[Math.floor(0.95 * N)];
    paths.forEach((p, k) => { row[`p${k}`] = p[i]; });
    return row;
  });
  const finals = paths.map((p) => p[p.length - 1]).sort((a, b) => a - b);
  const ruin = finals.filter((f) => f <= cap * 0.5).length / N;
  return {
    degenerate: false,
    chart,
    paths,
    p5: (finals[Math.floor(0.05 * N)] - cap) / cap,
    p50: (finals[Math.floor(0.5 * N)] - cap) / cap,
    p95: (finals[Math.floor(0.95 * N)] - cap) / cap,
    ruin,
  };
}



function DrawdownCard({ run }: { run: BacktestRun }) {
  const data = useMemo(() => {
    let peak = run.equity[0]?.equity ?? 0;
    return run.equity.map((p) => {
      peak = Math.max(peak, p.equity);
      const dd = peak > 0 ? (p.equity - peak) / peak : 0;
      return { t: p.t, dd };
    });
  }, [run.id]);
  // Empty equity → Math.min(...[]) is +Infinity; clamp to 0.
  const maxDD = data.length ? Math.min(...data.map((d) => d.dd)) : 0;
  return (
    <Card className="border-border bg-elevated p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-medium">Drawdown</div>
        <div className="font-mono text-[11px] text-muted-foreground">Max DD <span className="text-danger">{fmtPct(maxDD)}</span></div>
      </div>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs><linearGradient id="ddg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--danger)" stopOpacity={0.5} /><stop offset="100%" stopColor="var(--danger)" stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
            <XAxis dataKey="t" tickFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: "short" })} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
            <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => fmtPct(v)} />
            <Area type="monotone" dataKey="dd" stroke="var(--danger)" strokeWidth={1.5} fill="url(#ddg)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function histogram(values: number[], bins: number) {
  if (!values.length) return [] as { x: number; count: number }[];
  const min = Math.min(...values), max = Math.max(...values);
  const w = (max - min) / bins || 1;
  const buckets = Array.from({ length: bins }, (_, i) => ({ x: +(min + (i + 0.5) * w).toFixed(2), count: 0 }));
  for (const v of values) {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((v - min) / w)));
    buckets[idx].count++;
  }
  return buckets;
}

function RDistributionCard({ run }: { run: BacktestRun }) {
  const data = useMemo(() => histogram(run.trades.map((t) => t.pnlR), 24), [run.id]);
  return (
    <Card className="border-border bg-elevated p-4">
      <div className="mb-2 text-sm font-medium">Per-trade R distribution</div>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
            <XAxis dataKey="x" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} tickFormatter={(v) => v.toFixed(1)} />
            <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
            <Bar dataKey="count">
              {data.map((d, i) => <Cell key={i} fill={d.x >= 0 ? "var(--cyan)" : "var(--danger)"} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function TerminalValueCard({ run }: { run: BacktestRun }) {
  const degenerate = run.trades.length === 0 || !(run.params.capital > 0);
  const { data, p5, p50, p95 } = useMemo(() => {
    const rets = run.trades.map((t) => t.pnlR * 0.01);
    const N = 500, T = Math.min(rets.length, 120);
    const finals: number[] = [];
    for (let i = 0; i < N; i++) {
      let v = run.params.capital;
      for (let t = 0; t < T; t++) v = Math.max(v * (1 + (rets[Math.floor(Math.random() * rets.length)] ?? 0)), 0);
      finals.push(v);
    }
    finals.sort((a, b) => a - b);
    return {
      data: histogram(finals, 30),
      p5: finals[Math.floor(0.05 * N)],
      p50: finals[Math.floor(0.5 * N)],
      p95: finals[Math.floor(0.95 * N)],
    };
  }, [run.id]);
  if (degenerate) {
    return (
      <Card className="border-border bg-elevated p-4">
        <div className="mb-2 text-sm font-medium">Terminal-value distribution</div>
        <p className="text-sm text-muted-foreground">No closed trades to project from.</p>
      </Card>
    );
  }
  return (
    <Card className="border-border bg-elevated p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-sm font-medium">Terminal-value distribution</div>
        <div className="flex items-center gap-3 font-mono text-[11px] text-muted-foreground">
          <span>p5 <span className="text-danger">${(p5/1000).toFixed(1)}k</span></span>
          <span>p50 <span className="text-foreground">${(p50/1000).toFixed(1)}k</span></span>
          <span>p95 <span className="text-cyan">${(p95/1000).toFixed(1)}k</span></span>
        </div>
      </div>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
            <XAxis dataKey="x" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
            <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => v} labelFormatter={(v) => `$${Number(v).toLocaleString()}`} />
            <Bar dataKey="count">
              {data.map((d, i) => <Cell key={i} fill={d.x >= run.params.capital ? "var(--violet)" : "var(--danger)"} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
