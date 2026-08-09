import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { PieChart, Radio } from "lucide-react";
import type { BacktestAttribution } from "@/lib/types";

const money = (s: string | null | undefined) => {
  const n = Number(s ?? 0);
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
};
const pctOrDash = (n: number | null | undefined, dp = 0) =>
  n == null ? "—" : `${n.toFixed(dp)}%`;

function PnlCell({ value }: { value: string | null | undefined }) {
  const n = Number(value ?? 0);
  return <span className={cn("font-mono", n > 0 ? "text-cyan" : n < 0 ? "text-danger" : "text-muted-foreground")}>{money(value)}</span>;
}

export function AttributionCard({ attribution }: { attribution: BacktestAttribution }) {
  const by_symbol = attribution.by_symbol ?? [];
  const by_signal = attribution.by_signal ?? [];
  const untagged_trades = attribution.untagged_trades ?? 0;
  const num_closed_trades = attribution.num_closed_trades ?? 0;
  const hasSignals = by_signal.length > 0;

  return (
    <Card className="border-border bg-elevated">
      <div className="flex items-center gap-2 border-b border-border p-4 text-sm font-medium">
        <PieChart className="size-4 text-violet" /> Performance attribution — the “why”
      </div>

      <div className="grid gap-4 p-4 lg:grid-cols-2">
        {/* By symbol */}
        <div>
          <div className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">By symbol</div>
          <div className="overflow-hidden rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/20 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="p-2 text-left">Symbol</th>
                  <th className="p-2 text-right">Trades</th>
                  <th className="p-2 text-right">Win%</th>
                  <th className="p-2 text-right">Net P&L</th>
                  <th className="p-2 text-right">Share</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {by_symbol.map((s) => (
                  <tr key={s.symbol}>
                    <td className="p-2 font-medium">{s.symbol}</td>
                    <td className="p-2 text-right font-mono text-xs">{s.num_trades}</td>
                    <td className="p-2 text-right font-mono text-xs">{pctOrDash(s.win_rate_pct)}</td>
                    <td className="p-2 text-right"><PnlCell value={s.net_pnl} /></td>
                    <td className="p-2 text-right font-mono text-xs text-muted-foreground">{pctOrDash(s.pct_of_total_net_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* By signal */}
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            <Radio className="size-3" /> By signal
          </div>
          {hasSignals ? (
            <div className="overflow-hidden rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="bg-muted/20 text-[10px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="p-2 text-left">Signal</th>
                    <th className="p-2 text-right">Fired</th>
                    <th className="p-2 text-right">Trades</th>
                    <th className="p-2 text-right">Win%</th>
                    <th className="p-2 text-right">Net P&L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {by_signal.map((s) => (
                    <tr key={s.name}>
                      <td className="p-2 font-medium">{s.name}</td>
                      <td className="p-2 text-right font-mono text-xs text-muted-foreground">{s.num_fired}</td>
                      <td className="p-2 text-right font-mono text-xs">{s.num_trades}</td>
                      <td className="p-2 text-right font-mono text-xs">{pctOrDash(s.win_rate_pct)}</td>
                      <td className="p-2 text-right"><PnlCell value={s.net_pnl} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
              This strategy emits no signals, so per-filter attribution isn’t available.
              Add <code className="rounded bg-muted/40 px-1 text-xs">ctx.signal(name, passed=, value=)</code> on
              its entry conditions to see which filters drive returns.
            </div>
          )}
          {hasSignals && untagged_trades > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              {untagged_trades}/{num_closed_trades} trades carry no signal tag (unexplained by signals).
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
