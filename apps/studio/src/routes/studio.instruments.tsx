import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { Database, Search } from "lucide-react";
import {
  listInstruments,
  getInstrumentCoverage,
  type AssetClass,
  type Instrument,
} from "@/lib/api/system";

export const Route = createFileRoute("/studio/instruments")({
  head: () => ({ meta: [{ title: "Instruments — Bayn Studio" }] }),
  component: InstrumentsPage,
});

const CLASSES: Array<{ key: AssetClass | "all"; label: string }> = [
  { key: "all", label: "All" },
  { key: "crypto_spot", label: "Crypto" },
  { key: "equity", label: "Stocks" },
  { key: "option", label: "Options" },
];

const tickerOf = (canonical: string) => canonical.split("@")[0];

function fmtBars(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function fmtDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString(undefined, { year: "2-digit", month: "short", day: "numeric" });
}

function InstrumentsPage() {
  const [cls, setCls] = useState<AssetClass | "all">("all");
  const [q, setQ] = useState("");

  const assetClass = cls === "all" ? undefined : cls;

  const { data: instruments, isLoading } = useQuery({
    queryKey: ["instruments", cls],
    queryFn: () => listInstruments({ asset_class: assetClass, active: true }),
  });
  const { data: coverage } = useQuery({
    queryKey: ["instrumentCoverage", cls],
    queryFn: () => getInstrumentCoverage(assetClass),
  });

  const covMap = useMemo(() => {
    const m = new Map<string, { bars: number; first: string | null; last: string | null }>();
    for (const c of coverage ?? []) m.set(c.canonical_symbol, c);
    return m;
  }, [coverage]);

  const rows = useMemo(() => {
    const list = instruments ?? [];
    const needle = q.trim().toLowerCase();
    const filtered = needle
      ? list.filter(
          (i) =>
            tickerOf(i.canonical_symbol).toLowerCase().includes(needle) ||
            i.canonical_symbol.toLowerCase().includes(needle),
        )
      : list;
    // Sort: instruments with data first (by bar count desc), then the rest by symbol.
    return [...filtered].sort((a, b) => {
      const ca = covMap.get(a.canonical_symbol)?.bars ?? 0;
      const cb = covMap.get(b.canonical_symbol)?.bars ?? 0;
      if (cb !== ca) return cb - ca;
      return a.canonical_symbol.localeCompare(b.canonical_symbol);
    });
  }, [instruments, q, covMap]);

  const withData = rows.filter((r) => (covMap.get(r.canonical_symbol)?.bars ?? 0) > 0).length;

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Database className="size-6 text-violet" /> Instruments
        </h1>
        <p className="text-sm text-muted-foreground">
          The tradeable universe and how much historical data each symbol has. Symbols
          with bars are backtestable; those without will run but produce no trades.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-lg border border-border bg-elevated p-0.5">
          {CLASSES.map((c) => (
            <button
              key={c.key}
              onClick={() => setCls(c.key)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm transition-colors",
                cls === c.key ? "bg-violet/15 text-violet" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
        <div className="relative max-w-xs flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search e.g. SPY, BTC, AAPL"
            className="pl-8"
          />
        </div>
        <div className="ml-auto text-sm text-muted-foreground">
          {isLoading ? "Loading…" : `${rows.length} instruments · ${withData} with data`}
        </div>
      </div>

      <Card className="border-border bg-elevated">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/20 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="p-2 text-left">Ticker</th>
                <th className="p-2 text-left">Venue</th>
                <th className="p-2 text-left">Class</th>
                <th className="p-2 text-right">Bars (1d)</th>
                <th className="p-2 text-right">First</th>
                <th className="p-2 text-right">Last</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((i) => (
                <InstrumentRow key={i.id} i={i} cov={covMap.get(i.canonical_symbol)} />
              ))}
              {!isLoading && rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="p-8 text-center text-muted-foreground">
                    No instruments match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function InstrumentRow({
  i,
  cov,
}: {
  i: Instrument;
  cov?: { bars: number; first: string | null; last: string | null };
}) {
  const bars = cov?.bars ?? 0;
  const hasData = bars > 0;
  return (
    <tr className="hover:bg-muted/10">
      <td className="p-2 font-medium">{tickerOf(i.canonical_symbol)}</td>
      <td className="p-2 text-xs text-muted-foreground">{i.venue}</td>
      <td className="p-2 text-xs text-muted-foreground">
        {i.asset_class.replace("_spot", "")}
      </td>
      <td className={cn("p-2 text-right font-mono text-xs", hasData ? "text-foreground" : "text-muted-foreground/50")}>
        {hasData ? fmtBars(bars) : "—"}
      </td>
      <td className="p-2 text-right font-mono text-xs text-muted-foreground">{fmtDate(cov?.first ?? null)}</td>
      <td className="p-2 text-right font-mono text-xs text-muted-foreground">{fmtDate(cov?.last ?? null)}</td>
    </tr>
  );
}
