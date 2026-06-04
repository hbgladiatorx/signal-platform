import { createFileRoute, Link, useParams, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { zodValidator, fallback } from "@tanstack/zod-adapter";
import { z } from "zod";
import { getBacktestsForStrategy, getBacktest, getDevStrategy, submitStrategyToBayn, deployStrategyLive, runBacktest } from "@/lib/api/studio";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell,
  Line, LineChart,
} from "recharts";
import { ArrowLeft, Rocket, Send, CheckCircle2, ArrowRight, Activity, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { advanceStage, getStage, nextStage, STAGE_ORDER } from "@/lib/strategy-stage";
import { deployStageMeta, type DeployStage } from "@/lib/api/agent";
import type { BacktestRun } from "@/lib/types";

const searchSchema = z.object({
  runId: fallback(z.string().optional(), undefined),
});

export const Route = createFileRoute("/studio/backtests/$strategyId")({
  head: () => ({ meta: [{ title: "Backtest results — Bayn Studio" }] }),
  validateSearch: zodValidator(searchSchema),
  component: BacktestDetail,
});

const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`;

function BacktestDetail() {
  const { strategyId } = useParams({ from: "/studio/backtests/$strategyId" });
  const { runId } = Route.useSearch();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: runs } = useQuery({ queryKey: ["bts", strategyId], queryFn: () => getBacktestsForStrategy(strategyId) });
  const { data: strategy } = useQuery({ queryKey: ["devStrategy", strategyId], queryFn: () => getDevStrategy(strategyId) });

  const [selectedId, setSelectedId] = useState<string | undefined>(runId);
  useEffect(() => { if (runId) setSelectedId(runId); }, [runId]);

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
      toast.loading("Running out-of-sample test…", { id: "oos" });
      const oosParams = {
        ...run.params,
        startDate: run.params.endDate,
        endDate: new Date(+new Date(run.params.endDate) + 90 * 86_400_000).toISOString().slice(0, 10),
      };
      const r = await runBacktest(strategyId, oosParams);
      advanceStage(strategyId, "oos");
      toast.success("OOS passed", { id: "oos" });
      await qc.invalidateQueries({ queryKey: ["bts", strategyId] });
      navigate({ to: "/studio/backtests/$strategyId", params: { strategyId }, search: { runId: r.id } as never });
    },
    oos: async () => {
      advanceStage(strategyId, "forward");
      toast.success("Deployed to forward test (7-day window)");
    },
    forward: async () => {
      advanceStage(strategyId, "deployable");
      await deployStrategyLive(strategyId);
      toast.success("Strategy is live in your personal signals");
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
          {next && (
            <Button size="sm" className="bg-violet text-violet-foreground hover:bg-violet/90"
              onClick={() => stepFns[stage as Exclude<DeployStage, "draft">]?.()}>
              {nextStepLabel(stage)} <ArrowRight className="ml-1 size-3.5" />
            </Button>
          )}
        </div>
        <Stepper current={stage} />
      </Card>

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
        <Button variant="outline" onClick={async () => { await deployStrategyLive(strategyId); advanceStage(strategyId, "deployable"); toast.success("Deployed to live forward test"); }}>
          <Rocket className="mr-1 size-4" /> Deploy Live
        </Button>
        <Button className="bg-violet text-violet-foreground hover:bg-violet/90"
          onClick={async () => { await submitStrategyToBayn(strategyId); advanceStage(strategyId, "eligible"); toast.success("Submitted to Bayn for review"); }}>
          <Send className="mr-1 size-4" /> Submit to Bayn
        </Button>
      </div>
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
  const cap = run.params.capital;
  const ruin = finals.filter((f) => f <= cap * 0.5).length / N;
  return {
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
  const maxDD = Math.min(...data.map((d) => d.dd));
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
