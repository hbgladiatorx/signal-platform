import { createFileRoute, Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getBacktestsForStrategy, getDevStrategy, submitStrategyToBayn, deployStrategyLive } from "@/lib/api/studio";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell } from "recharts";
import { ArrowLeft, Rocket, Send } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/studio/backtests/$strategyId")({
  head: () => ({ meta: [{ title: "Backtest results — Bayn Studio" }] }),
  component: BacktestDetail,
});

const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`;

function BacktestDetail() {
  const { strategyId } = useParams({ from: "/studio/backtests/$strategyId" });
  const { data: runs } = useQuery({ queryKey: ["bts", strategyId], queryFn: () => getBacktestsForStrategy(strategyId) });
  const { data: strategy } = useQuery({ queryKey: ["devStrategy", strategyId], queryFn: () => getDevStrategy(strategyId) });
  const [runId, setRunId] = useState<string | undefined>(undefined);
  const run = runs?.find((r) => r.id === runId) ?? runs?.[0];

  if (!strategy) return <div className="p-6 text-muted-foreground">Loading…</div>;
  if (!run) return <div className="p-6 text-muted-foreground">No backtest runs yet.</div>;

  const stats = run.stats;

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild variant="ghost" size="sm"><Link to="/studio/backtests"><ArrowLeft className="mr-1 size-4" /> Backtests</Link></Button>
        <div className="flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">{strategy.name}</h1>
          <p className="text-sm text-muted-foreground">Backtest results · {new Date(run.ranAt).toLocaleString()}</p>
        </div>
        <Select value={run.id} onValueChange={setRunId}>
          <SelectTrigger className="w-64 bg-elevated"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(runs ?? []).map((r) => <SelectItem key={r.id} value={r.id}>Run {new Date(r.ranAt).toLocaleDateString()}</SelectItem>)}
          </SelectContent>
        </Select>
        <Button variant="outline" onClick={async () => { await deployStrategyLive(strategyId); toast.success("Deployed to live forward test"); }}>
          <Rocket className="mr-1 size-4" /> Deploy Live
        </Button>
        <Button className="bg-violet text-violet-foreground hover:bg-violet/90" onClick={async () => { await submitStrategyToBayn(strategyId); toast.success("Submitted to Bayn for review"); }}>
          <Send className="mr-1 size-4" /> Submit to Bayn
        </Button>
      </div>

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
    </div>
  );
}
