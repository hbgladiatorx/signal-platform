"use client";

import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import { cn } from "@/lib/utils";
import type {
  HealthResponse,
  IngestionInstrumentStatus,
  StreamStatus,
  SystemHealthDetail,
  TableStats,
} from "@/lib/types";

// ----- Threshold definitions -----

const INGESTION_HEALTHY_S = 30;
const INGESTION_WARN_S = 120;

const PERSISTENCE_HEALTHY_PENDING = 100;
const PERSISTENCE_WARN_PENDING = 1_000;

const STREAM_HEALTHY_LEN = 50_000;
const STREAM_WARN_LEN = 100_000;

const DURATION_HEALTHY_MS = 100;
const DURATION_WARN_MS = 500;

type Level = "ok" | "warn" | "crit" | "neutral";

function ingestionLevel(age_s: number | null): Level {
  if (age_s === null) return "neutral";
  if (age_s < INGESTION_HEALTHY_S) return "ok";
  if (age_s < INGESTION_WARN_S) return "warn";
  return "crit";
}

function pendingLevel(pending: number): Level {
  if (pending < PERSISTENCE_HEALTHY_PENDING) return "ok";
  if (pending < PERSISTENCE_WARN_PENDING) return "warn";
  return "crit";
}

function streamLengthLevel(length: number): Level {
  if (length < STREAM_HEALTHY_LEN) return "ok";
  if (length < STREAM_WARN_LEN) return "warn";
  return "crit";
}

function durationLevel(ms: number): Level {
  if (ms < DURATION_HEALTHY_MS) return "ok";
  if (ms < DURATION_WARN_MS) return "warn";
  return "crit";
}

// ----- Display helpers -----

function dotClass(level: Level): string {
  switch (level) {
    case "ok":
      return "bg-green-500";
    case "warn":
      return "bg-yellow-500";
    case "crit":
      return "bg-red-500";
    default:
      return "bg-gray-300";
  }
}

function textClass(level: Level): string {
  switch (level) {
    case "ok":
      return "text-green-700";
    case "warn":
      return "text-yellow-700";
    case "crit":
      return "text-red-700";
    default:
      return "text-gray-500";
  }
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  if (seconds < 3_600) return `${(seconds / 60).toFixed(1)}m`;
  if (seconds < 86_400) return `${(seconds / 3_600).toFixed(1)}h`;
  return `${(seconds / 86_400).toFixed(1)}d`;
}

function formatTs(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toISOString().replace("T", " ").slice(0, 19);
}

function formatNumber(n: number): string {
  return n.toLocaleString();
}

// ----- Page -----

export default function SystemHealthPage() {
  const api = useApi();

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<HealthResponse>("/health"),
    refetchInterval: 30_000,
  });

  const detailQuery = useQuery({
    queryKey: ["system", "health", "detail"],
    queryFn: () => api.get<SystemHealthDetail>("/system/health/detail"),
    refetchInterval: 30_000,
  });

  const detail = detailQuery.data;

  // ----- Overall status summary -----
  const summary = (() => {
    if (!detail) return null;
    const issues: { kind: Level; label: string }[] = [];

    for (const inst of detail.ingestion) {
      const tLevel = ingestionLevel(inst.last_trade_age_s);
      const qLevel = ingestionLevel(inst.last_quote_age_s);
      if (tLevel === "crit")
        issues.push({ kind: "crit", label: `${inst.canonical_symbol}: no trades` });
      else if (tLevel === "warn")
        issues.push({ kind: "warn", label: `${inst.canonical_symbol}: trades stale` });
      if (qLevel === "crit")
        issues.push({ kind: "crit", label: `${inst.canonical_symbol}: no quotes` });
      else if (qLevel === "warn")
        issues.push({ kind: "warn", label: `${inst.canonical_symbol}: quotes stale` });
    }

    const pLevel = pendingLevel(detail.persistence_pending_total);
    if (pLevel === "crit") issues.push({ kind: "crit", label: "Persistence worker far behind" });
    else if (pLevel === "warn") issues.push({ kind: "warn", label: "Persistence worker lagging" });

    const dLevel = durationLevel(detail.duration_ms);
    if (dLevel === "crit") issues.push({ kind: "crit", label: "Health endpoint slow" });

    return { issues };
  })();

  const overallLevel: Level = summary
    ? summary.issues.some((i) => i.kind === "crit")
      ? "crit"
      : summary.issues.some((i) => i.kind === "warn")
        ? "warn"
        : "ok"
    : "neutral";

  return (
    <AppShell title="System Health">
      <div className="space-y-6">
        {/* Top-level status banner */}
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex items-center gap-3">
            <span
              className={cn(
                "h-2.5 w-2.5 rounded-full",
                dotClass(overallLevel),
                overallLevel === "ok" && "animate-pulse",
              )}
            />
            <div>
              <h2 className={cn("text-base font-semibold", textClass(overallLevel))}>
                {overallLevel === "ok"
                  ? "All systems normal"
                  : overallLevel === "warn"
                    ? "Degraded"
                    : overallLevel === "crit"
                      ? "Critical issues"
                      : "Checking…"}
              </h2>
              <p className="text-xs text-gray-500">
                Auto-refreshes every 30s · Last refresh{" "}
                {detail?.ts ? formatTs(detail.ts) : "—"} ·{" "}
                <span className={textClass(durationLevel(detail?.duration_ms ?? 0))}>
                  {detail?.duration_ms.toFixed(1)} ms
                </span>
              </p>
            </div>
          </div>
          {summary && summary.issues.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm">
              {summary.issues.map((issue, i) => (
                <li key={i} className="flex items-center gap-2">
                  <span
                    className={cn("h-1.5 w-1.5 rounded-full", dotClass(issue.kind))}
                  />
                  <span className={textClass(issue.kind)}>{issue.label}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Three stat cards: API alive, instruments, persistence pending */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatCard
            label="API"
            value={healthQuery.data?.status ?? "—"}
            level={healthQuery.data?.status === "alive" ? "ok" : "crit"}
            hint={healthQuery.data?.ts ? formatTs(healthQuery.data.ts) : ""}
          />
          <StatCard
            label="Instruments active"
            value={
              detail
                ? `${detail.instruments_active}/${detail.instruments_total}`
                : "—"
            }
            level="neutral"
          />
          <StatCard
            label="Persistence backlog"
            value={
              detail ? formatNumber(detail.persistence_pending_total) : "—"
            }
            level={
              detail
                ? pendingLevel(detail.persistence_pending_total)
                : "neutral"
            }
            hint="pending messages"
          />
        </div>

        {/* Ingestion freshness table */}
        <Section title="Ingestion freshness">
          {detailQuery.isLoading && (
            <div className="px-6 py-8 text-center text-sm text-gray-500">
              Loading…
            </div>
          )}
          {detailQuery.error && (
            <div className="px-6 py-8 text-center text-sm text-red-600">
              {(detailQuery.error as Error).message}
            </div>
          )}
          {detail && (
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-6 py-2 font-medium">Symbol</th>
                  <th className="px-6 py-2 font-medium">Venue</th>
                  <th className="px-6 py-2 font-medium">Last trade</th>
                  <th className="px-6 py-2 font-medium">Last quote</th>
                  <th className="px-6 py-2 font-medium">Trades (5m)</th>
                  <th className="px-6 py-2 font-medium">Quotes (5m)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {detail.ingestion.map((row) => (
                  <IngestionRow key={row.canonical_symbol} row={row} />
                ))}
              </tbody>
            </table>
          )}
        </Section>

        {/* Redis streams table */}
        <Section title="Redis streams">
          {detail && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-6 py-2 font-medium">Stream</th>
                    <th className="px-6 py-2 font-medium">Length</th>
                    <th className="px-6 py-2 font-medium">Consumer groups</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {detail.streams.map((s) => (
                    <StreamRow key={s.stream} stream={s} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>

        {/* Database hypertables */}
        <Section title="Database hypertables">
          {detail && (
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-6 py-2 font-medium">Table</th>
                  <th className="px-6 py-2 font-medium">Approx rows</th>
                  <th className="px-6 py-2 font-medium">Earliest</th>
                  <th className="px-6 py-2 font-medium">Latest</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {detail.tables.map((t) => (
                  <TableRow key={t.name} table={t} />
                ))}
              </tbody>
            </table>
          )}
        </Section>
      </div>
    </AppShell>
  );
}

// ----- Components -----

function StatCard({
  label,
  value,
  level,
  hint,
}: {
  label: string;
  value: string;
  level: Level;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-gray-500">
        <span className={cn("h-1.5 w-1.5 rounded-full", dotClass(level))} />
        {label}
      </div>
      <div className={cn("mt-2 text-2xl font-semibold", textClass(level))}>
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-gray-400">{hint}</div>}
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-6 py-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-gray-500">
          {title}
        </h2>
      </div>
      {children}
    </div>
  );
}

function IngestionRow({ row }: { row: IngestionInstrumentStatus }) {
  const tLevel = ingestionLevel(row.last_trade_age_s);
  const qLevel = ingestionLevel(row.last_quote_age_s);
  return (
    <tr>
      <td className="px-6 py-2 font-mono">{row.canonical_symbol}</td>
      <td className="px-6 py-2 text-gray-600">{row.venue}</td>
      <td className="px-6 py-2">
        <div className="flex items-center gap-2">
          <span className={cn("h-1.5 w-1.5 rounded-full", dotClass(tLevel))} />
          <span className={cn("font-mono", textClass(tLevel))}>
            {formatAge(row.last_trade_age_s)}
          </span>
        </div>
      </td>
      <td className="px-6 py-2">
        <div className="flex items-center gap-2">
          <span className={cn("h-1.5 w-1.5 rounded-full", dotClass(qLevel))} />
          <span className={cn("font-mono", textClass(qLevel))}>
            {formatAge(row.last_quote_age_s)}
          </span>
        </div>
      </td>
      <td className="px-6 py-2 font-mono">{formatNumber(row.trades_last_5m)}</td>
      <td className="px-6 py-2 font-mono">{formatNumber(row.quotes_last_5m)}</td>
    </tr>
  );
}

function StreamRow({ stream }: { stream: StreamStatus }) {
  const lenLevel = streamLengthLevel(stream.length);
  return (
    <tr>
      <td className="px-6 py-2 font-mono">{stream.stream}</td>
      <td className="px-6 py-2">
        <span className={cn("font-mono", textClass(lenLevel))}>
          {formatNumber(stream.length)}
        </span>
      </td>
      <td className="px-6 py-2">
        <ul className="space-y-1">
          {stream.groups.length === 0 && (
            <li className="text-gray-400">no groups</li>
          )}
          {stream.groups.map((g) => {
            const pLevel = pendingLevel(g.pending);
            return (
              <li key={g.name} className="flex items-center gap-3 text-xs">
                <span className="font-mono text-gray-700">{g.name}</span>
                <span className="text-gray-500">
                  consumers: <span className="font-mono">{g.consumers}</span>
                </span>
                <span className="text-gray-500">
                  pending:{" "}
                  <span className={cn("font-mono", textClass(pLevel))}>
                    {g.pending}
                  </span>
                </span>
                {g.lag !== null && (
                  <span className="text-gray-500">
                    lag: <span className="font-mono">{g.lag}</span>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </td>
    </tr>
  );
}

function TableRow({ table }: { table: TableStats }) {
  return (
    <tr>
      <td className="px-6 py-2 font-mono">{table.name}</td>
      <td className="px-6 py-2 font-mono">
        {formatNumber(table.approximate_rows)}
      </td>
      <td className="px-6 py-2 font-mono text-xs text-gray-600">
        {formatTs(table.earliest_ts)}
      </td>
      <td className="px-6 py-2 font-mono text-xs text-gray-600">
        {formatTs(table.latest_ts)}
      </td>
    </tr>
  );
}
