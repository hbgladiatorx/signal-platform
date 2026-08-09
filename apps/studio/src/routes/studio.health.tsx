import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { Activity, AlertTriangle, CheckCircle2, Loader2, RefreshCw } from "lucide-react";
import {
  getSystemHealth,
  type IngestionInstrumentStatus,
  type SystemHealthDetail,
} from "@/lib/api/system";

export const Route = createFileRoute("/studio/health")({
  head: () => ({ meta: [{ title: "System health — Bayn Studio" }] }),
  component: HealthPage,
});

const fmtAge = (s: number | null): string => {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${(s / 3600).toFixed(1)}h`;
  return `${(s / 86400).toFixed(1)}d`;
};

const fmtRows = (n: number): string => {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
};

// Freshness thresholds (seconds): markets close, so "stale" is heuristic.
const freshTone = (ageS: number | null): "ok" | "warn" | "stale" => {
  if (ageS == null) return "stale";
  if (ageS <= 120) return "ok";
  if (ageS <= 3600) return "warn";
  return "stale";
};

function HealthPage() {
  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ["systemHealth"],
    queryFn: getSystemHealth,
    refetchInterval: 15_000,
  });

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Activity className="size-6 text-violet" /> System health
          </h1>
          <p className="text-sm text-muted-foreground">
            Live ingestion freshness, message-bus depth, and storage. Auto-refreshes every 15s.
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-1.5 rounded-md border border-border bg-elevated px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          {isFetching ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
          Refresh
        </button>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !data ? (
        <Card className="border-dashed border-border bg-elevated p-8 text-center text-sm text-muted-foreground">
          Couldn’t load system health.
        </Card>
      ) : (
        <HealthBody data={data} />
      )}
    </div>
  );
}

function HealthBody({ data }: { data: SystemHealthDetail }) {
  const backlog = data.persistence_pending_total + data.ws_broadcast_pending_total;
  const flowing = data.ingestion.filter((i) => freshTone(i.last_trade_age_s) === "ok").length;

  return (
    <div className="space-y-5">
      {/* Stat tiles */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Active instruments" value={`${data.instruments_active}`} sub={`of ${data.instruments_total}`} />
        <Stat label="Flowing now" value={`${flowing}`} sub="≤2m fresh" tone={flowing > 0 ? "ok" : "warn"} />
        <Stat
          label="Persistence backlog"
          value={fmtRows(data.persistence_pending_total)}
          tone={data.persistence_pending_total > 5000 ? "warn" : "ok"}
        />
        <Stat
          label="WS broadcast backlog"
          value={fmtRows(data.ws_broadcast_pending_total)}
          tone={data.ws_broadcast_pending_total > 5000 ? "warn" : "ok"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Ingestion freshness */}
        <Card className="border-border bg-elevated">
          <div className="flex items-center justify-between border-b border-border p-3">
            <span className="text-sm font-medium">Ingestion freshness</span>
            <span className="text-xs text-muted-foreground">{data.ingestion.length} instruments</span>
          </div>
          <div className="max-h-[28rem] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="p-2 text-left">Symbol</th>
                  <th className="p-2 text-right">Last trade</th>
                  <th className="p-2 text-right">Trades 5m</th>
                  <th className="p-2 text-right">Last quote</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.ingestion.map((i) => (
                  <IngestionRow key={`${i.canonical_symbol}`} i={i} />
                ))}
                {data.ingestion.length === 0 && (
                  <tr>
                    <td colSpan={4} className="p-6 text-center text-muted-foreground">No active instruments.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="space-y-4">
          {/* Streams */}
          <Card className="border-border bg-elevated">
            <div className="border-b border-border p-3 text-sm font-medium">Message-bus streams</div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/20 text-[10px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="p-2 text-left">Stream</th>
                    <th className="p-2 text-right">Depth</th>
                    <th className="p-2 text-right">Groups</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {data.streams.map((s) => (
                    <tr key={s.stream} className="hover:bg-muted/10">
                      <td className="p-2 font-mono text-xs">{s.stream}</td>
                      <td className={cn("p-2 text-right font-mono text-xs", s.length > 5000 ? "text-warn" : "text-foreground")}>
                        {fmtRows(s.length)}
                      </td>
                      <td className="p-2 text-right font-mono text-xs text-muted-foreground">{s.groups.length}</td>
                    </tr>
                  ))}
                  {data.streams.length === 0 && (
                    <tr><td colSpan={3} className="p-4 text-center text-muted-foreground">No streams.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Tables */}
          <Card className="border-border bg-elevated">
            <div className="border-b border-border p-3 text-sm font-medium">Storage</div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/20 text-[10px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="p-2 text-left">Table</th>
                    <th className="p-2 text-right">~Rows</th>
                    <th className="p-2 text-right">Latest</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {data.tables.map((t) => (
                    <tr key={t.name} className="hover:bg-muted/10">
                      <td className="p-2 font-mono text-xs">{t.name}</td>
                      <td className="p-2 text-right font-mono text-xs">{fmtRows(t.approximate_rows)}</td>
                      <td className="p-2 text-right font-mono text-xs text-muted-foreground">
                        {t.latest_ts ? new Date(t.latest_ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      </div>

      <p className="text-right text-[11px] text-muted-foreground">
        snapshot {new Date(data.ts).toLocaleTimeString()} · {data.duration_ms.toFixed(0)}ms · backlog {fmtRows(backlog)}
      </p>
    </div>
  );
}

function IngestionRow({ i }: { i: IngestionInstrumentStatus }) {
  const tone = freshTone(i.last_trade_age_s);
  return (
    <tr className="hover:bg-muted/10">
      <td className="p-2">
        <span className="inline-flex items-center gap-1.5">
          <span
            className={cn(
              "size-1.5 rounded-full",
              tone === "ok" ? "bg-success" : tone === "warn" ? "bg-warn" : "bg-muted-foreground/40",
            )}
          />
          <span className="font-medium">{i.canonical_symbol.split("@")[0]}</span>
        </span>
      </td>
      <td className={cn("p-2 text-right font-mono text-xs", tone === "ok" ? "text-success" : tone === "warn" ? "text-warn" : "text-muted-foreground")}>
        {fmtAge(i.last_trade_age_s)}
      </td>
      <td className="p-2 text-right font-mono text-xs text-muted-foreground">{i.trades_last_5m}</td>
      <td className="p-2 text-right font-mono text-xs text-muted-foreground">{fmtAge(i.last_quote_age_s)}</td>
    </tr>
  );
}

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "ok" | "warn";
}) {
  return (
    <Card className="border-border bg-elevated p-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</span>
        {tone === "ok" ? (
          <CheckCircle2 className="size-3.5 text-success" />
        ) : tone === "warn" ? (
          <AlertTriangle className="size-3.5 text-warn" />
        ) : null}
      </div>
      <div className="mt-1 font-mono text-xl font-semibold">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
    </Card>
  );
}
