import { createFileRoute } from "@tanstack/react-router";
import { Card } from "@/components/ui/card";
import {
  Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { format } from "date-fns";

export const Route = createFileRoute("/studio/earnings")({
  head: () => ({ meta: [{ title: "Earnings — Bayn Studio" }] }),
  component: EarningsPage,
});

const months = Array.from({ length: 12 }).map((_, i) => {
  const d = new Date();
  d.setMonth(d.getMonth() - (11 - i));
  return { t: d.toISOString(), revenue: 800 + i * 220 + (i % 3) * 140 };
});

const totalRevenue = months.reduce((a, b) => a + b.revenue, 0);

function EarningsPage() {
  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Earnings</h1>
        <p className="text-sm text-muted-foreground font-mono">// revenue share from published strategies</p>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Last 12 months" value={`$${totalRevenue.toLocaleString()}`} accent />
        <Stat label="This month" value={`$${months[11].revenue.toLocaleString()}`} />
        <Stat label="Published strategies" value="3" />
        <Stat label="Active subscribers" value="2,468" />
      </div>
      <Card className="border-border bg-elevated p-4">
        <h2 className="mb-3 text-sm font-semibold">Monthly revenue</h2>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={months}>
              <defs>
                <linearGradient id="rg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--gold)" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="var(--gold)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
              <XAxis dataKey="t" tickFormatter={(v) => format(new Date(v), "MMM")} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${v}`} />
              <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => `$${v.toLocaleString()}`} />
              <Area type="monotone" dataKey="revenue" stroke="var(--gold)" strokeWidth={2} fill="url(#rg)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <Card className="border-border bg-elevated p-4">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-2xl ${accent ? "text-gold" : ""}`}>{value}</div>
    </Card>
  );
}
