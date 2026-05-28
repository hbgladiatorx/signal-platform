import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { getEarnings } from "@/lib/api/studio";
import { Card } from "@/components/ui/card";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Wallet } from "lucide-react";

export const Route = createFileRoute("/studio/earnings")({
  head: () => ({ meta: [{ title: "Earnings — Bayn Studio" }] }),
  component: Earnings,
});

const fmtUSD = (n: number) => n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });

function Earnings() {
  const { data } = useQuery({ queryKey: ["earnings"], queryFn: getEarnings });
  const total = (data ?? []).reduce((s, d) => s + d.amount, 0);
  const nextPayout = new Date(); nextPayout.setDate(1); nextPayout.setMonth(nextPayout.getMonth() + 1);

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Earnings</h1>
        <p className="text-sm text-muted-foreground">Revenue share from strategies published in Bayn's catalog.</p>
      </div>

      {!data?.length ? (
        <Card className="border-border bg-elevated p-10 text-center text-sm text-muted-foreground">
          <Wallet className="mx-auto mb-3 size-8 opacity-50" />
          Build a strategy. Pass the pipeline. Earn revenue share when Bayn publishes it.
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <KPI label="Total earned" value={fmtUSD(total)} />
            <KPI label="Last month" value={fmtUSD(data[data.length - 1]?.amount ?? 0)} />
            <KPI label="Next payout" value={nextPayout.toLocaleDateString(undefined, { month: "long", day: "numeric" })} />
          </div>

          <Card className="border-border bg-elevated p-4">
            <div className="mb-2 text-sm font-medium">Monthly trend</div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data}>
                  <defs><linearGradient id="erng" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--violet)" stopOpacity={0.4} /><stop offset="100%" stopColor="var(--violet)" stopOpacity={0} /></linearGradient></defs>
                  <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${v}`} />
                  <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => fmtUSD(v)} />
                  <Area type="monotone" dataKey="amount" stroke="var(--violet)" strokeWidth={2} fill="url(#erng)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card className="border-border bg-elevated">
            <div className="border-b border-border p-4 text-sm font-medium">Payout history</div>
            <table className="w-full text-sm">
              <thead className="bg-muted/20 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr><th className="p-2 text-left">Month</th><th className="p-2 text-left">Strategy</th><th className="p-2 text-right">Subscribers</th><th className="p-2 text-right">Amount</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {[...data].reverse().map((d) => (
                  <tr key={d.month}>
                    <td className="p-2 font-mono">{d.month}</td>
                    <td className="p-2">{d.strategyName}</td>
                    <td className="p-2 text-right font-mono">{d.subscribers}</td>
                    <td className="p-2 text-right font-mono text-violet">{fmtUSD(d.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}

function KPI({ label, value }: { label: string; value: string }) {
  return (
    <Card className="border-border bg-elevated p-4">
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-2xl text-violet">{value}</div>
    </Card>
  );
}
