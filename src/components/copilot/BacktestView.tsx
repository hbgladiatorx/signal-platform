// Backtest results for the copilot workspace. When the user prompts "backtest
// it", the copilot runs it and this shows all the data: headline metrics, the
// equity curve, the AI analysis, per-symbol/-signal attribution, and trades.
// Reuses the same cards the standalone backtests page uses.
import { useQuery } from "@tanstack/react-query";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { getBacktest } from "@/lib/api/studio";
import { AnalysisCard } from "@/components/studio/AnalysisCard";
import { AttributionCard } from "@/components/studio/AttributionCard";
import { ModelCard } from "@/components/studio/ModelCard";
import { CardErrorBoundary } from "@/components/common/CardErrorBoundary";

const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`;

export function BacktestView({
  backtestId,
  status,
}: {
  backtestId: string | null;
  status?: string | null;
}) {
  const running = status === "pending" || status === "running";
  const { data: run, isLoading } = useQuery({
    queryKey: ["bt", backtestId],
    queryFn: () => getBacktest(backtestId!),
    enabled: !!backtestId && !running,
    refetchInterval: running ? 4000 : false,
  });

  if (!backtestId) {
    return (
      <Empty>No backtest yet — ask the copilot to run one and the results land here.</Empty>
    );
  }
  if (running) {
    return (
      <div className="grid h-full place-items-center">
        <div className="flex flex-col items-center gap-3 text-muted-foreground">
          <Loader2 className="size-6 animate-spin text-violet" />
          <div className="text-sm">Backtest running on the worker…</div>
        </div>
      </div>
    );
  }
  if (isLoading) {
    return (
      <div className="grid h-full place-items-center text-muted-foreground">
        <Loader2 className="size-5 animate-spin" />
      </div>
    );
  }
  if (!run) return <Empty>Couldn't load this backtest.</Empty>;

  const s = run.stats;
  const thin = (s.totalTrades ?? 0) < 30;

  return (
    <div className="space-y-4 p-1">
      {thin && (
        <div className="rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          Only {s.totalTrades} closed trades — too few to trust the ratios. Ask the copilot to
          widen the date range or use a lower timeframe.
        </div>
      )}

      {/* Headline metrics */}
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        {([
          ["Return", fmtPct(s.totalReturn), s.totalReturn >= 0],
          ["CAGR", fmtPct(s.cagr), s.cagr >= 0],
          ["Sharpe", s.sharpe.toFixed(2), s.sharpe >= 1],
          ["Max DD", fmtPct(s.maxDrawdown), false],
          ["Win rate", `${(s.winRate * 100).toFixed(0)}%`, s.winRate >= 0.5],
          ["Profit factor", s.profitFactor.toFixed(2), s.profitFactor >= 1],
          ["Trades", String(s.totalTrades), true],
          ["Capital", `$${run.params.capital.toLocaleString()}`, true],
        ] as [string, string, boolean][]).map(([k, v, good]) => (
          <Card key={k} className="border-border bg-elevated p-2.5">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{k}</div>
            <div className={cn("mt-0.5 font-mono text-base tabular-nums", good ? "text-foreground" : "text-danger")}>{v}</div>
          </Card>
        ))}
      </div>

      {/* Equity curve */}
      {run.equity.length > 0 && (
        <Card className="border-border bg-elevated p-4">
          <div className="mb-2 text-sm font-medium">Equity curve</div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={run.equity}>
                <defs>
                  <linearGradient id="cpEq" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--violet)" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="var(--violet)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
                <XAxis dataKey="t" tickFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: "short" })} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                <Area type="monotone" dataKey="equity" stroke="var(--violet)" strokeWidth={2} fill="url(#cpEq)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {/* AI analysis + attribution + signal-edge model */}
      {run.analysis && (
        <CardErrorBoundary label="AI analysis">
          <AnalysisCard analysis={run.analysis} backtestId={run.id} graph={null} />
        </CardErrorBoundary>
      )}
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

      {/* Trades */}
      {run.trades.length > 0 && (
        <Card className="border-border bg-elevated">
          <div className="border-b border-border p-3 text-sm font-medium">
            Trades · {run.trades.length}
          </div>
          <div className="max-h-80 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/30 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="p-2 text-left">Entry</th>
                  <th className="p-2 text-left">Exit</th>
                  <th className="p-2 text-left">Symbol</th>
                  <th className="p-2 text-left">Side</th>
                  <th className="p-2 text-right">P&L %</th>
                  <th className="p-2 text-right">R</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border font-mono text-xs">
                {run.trades.slice(0, 100).map((t) => (
                  <tr key={t.id}>
                    <td className="p-2">{new Date(t.entryDate).toLocaleDateString()}</td>
                    <td className="p-2">{new Date(t.exitDate).toLocaleDateString()}</td>
                    <td className="p-2">{t.symbol}</td>
                    <td className={cn("p-2", t.direction === "LONG" ? "text-cyan" : "text-danger")}>{t.direction}</td>
                    <td className={cn("p-2 text-right", t.pnlPct >= 0 ? "text-cyan" : "text-danger")}>{fmtPct(t.pnlPct)}</td>
                    <td className={cn("p-2 text-right", t.pnlR >= 0 ? "text-cyan" : "text-danger")}>{t.pnlR.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid h-full place-items-center px-6 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}
