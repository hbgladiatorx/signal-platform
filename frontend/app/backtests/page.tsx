"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/nav/AppShell";
import type { BacktestStatus, BacktestSummary } from "@/lib/backtest-types";
import { useApi } from "@/lib/useApi";

export default function BacktestsListPage() {
  const api = useApi();
  const router = useRouter();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["backtests"],
    queryFn: () => api.get<BacktestSummary[]>("/backtests"),
    // Refresh every 3s while there are active runs
    refetchInterval: (q) => {
      const rows = q.state.data as BacktestSummary[] | undefined;
      if (!rows) return false;
      const hasActive = rows.some(
        (r) => r.status === "pending" || r.status === "running",
      );
      return hasActive ? 3000 : false;
    },
  });

  return (
    <AppShell title="Backtests">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-navy-700">
              Your backtests
            </h2>
            <p className="mt-1 text-xs text-gray-500">
              Strategies run against historical data. Click a row to see
              detailed results. Auto-refreshes every 3 seconds while runs
              are active.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => refetch()}
              className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Refresh
            </button>
            <Link
              href="/backtests/sweep"
              className="px-3 py-1.5 text-sm border border-slate-300 rounded hover:bg-slate-50"
            >
              Sweep
            </Link>
            <Link
              href="/backtests/new"
              className="rounded-md bg-navy-600 px-4 py-2 text-sm font-medium text-white hover:bg-navy-700"
            >
              New backtest
            </Link>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white">
          {isLoading && (
            <div className="px-6 py-12 text-center text-sm text-gray-500">
              Loading…
            </div>
          )}

          {error && (
            <div className="px-6 py-12 text-center text-sm text-red-600">
              Failed to load backtests: {(error as Error).message}
            </div>
          )}

          {data && data.length === 0 && (
            <div className="px-6 py-12 text-center text-sm text-gray-500">
              No backtests yet.{" "}
              <Link
                href="/backtests/new"
                className="text-navy-600 hover:underline"
              >
                Run your first
              </Link>
              .
            </div>
          )}

          {data && data.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">Strategy</th>
                    <th className="px-3 py-2 font-medium">Symbols</th>
                    <th className="px-3 py-2 font-medium">Res.</th>
                    <th className="px-3 py-2 font-medium">Period</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 text-right font-medium">Return</th>
                    <th className="px-3 py-2 text-right font-medium">Sharpe</th>
                    <th className="px-3 py-2 text-right font-medium">Max DD</th>
                    <th className="px-3 py-2 text-right font-medium">Trades</th>
                    <th className="px-3 py-2 text-right font-medium">Win %</th>
                    <th className="px-3 py-2 font-medium whitespace-nowrap">Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.map((bt) => {
                    const days = calcDaysTested(bt);
                    return (
                      <tr
                        key={bt.id}
                        role="button"
                        tabIndex={0}
                        onClick={() => router.push(`/backtests/${bt.id}`)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            router.push(`/backtests/${bt.id}`);
                          }
                        }}
                        className="cursor-pointer transition-colors hover:bg-navy-50/40 focus:bg-navy-50/40 focus:outline-none"
                      >
                        <td className="px-3 py-3">
                          <Link
                            href={`/backtests/${bt.id}`}
                            onClick={(e) => e.stopPropagation()}
                            className="font-mono text-xs text-navy-600 hover:underline"
                          >
                            {bt.strategy_name}
                          </Link>
                        </td>
                        <td className="px-3 py-3 font-mono text-xs text-gray-600 whitespace-nowrap">
                          {bt.symbols.join(", ")}
                        </td>
                        <td className="px-3 py-3 text-gray-600">
                          {bt.bar_resolution}
                        </td>
                        <td
                          className={`px-3 py-3 font-mono text-xs whitespace-nowrap ${sampleSizeColor(days)}`}
                          title={
                            days != null
                              ? sampleSizeTooltip(days)
                              : undefined
                          }
                        >
                          {days != null ? fmtDaysCompact(days) : "—"}
                        </td>
                        <td className="px-3 py-3">
                          <StatusBadge status={bt.status} />
                        </td>
                        <td
                          className={`px-3 py-3 text-right font-mono whitespace-nowrap ${returnColor(bt.total_return_pct)}`}
                        >
                          {fmtPct(bt.total_return_pct)}
                        </td>
                        <td className="px-3 py-3 text-right font-mono text-gray-700 whitespace-nowrap">
                          {fmtNum(bt.sharpe_ratio, 2)}
                        </td>
                        <td className="px-3 py-3 text-right font-mono text-gray-700 whitespace-nowrap">
                          {fmtPct(bt.max_drawdown_pct)}
                        </td>
                        <td className="px-3 py-3 text-right font-mono text-gray-700">
                          {bt.num_closed_trades ?? "—"}
                        </td>
                        <td className="px-3 py-3 text-right font-mono text-gray-700 whitespace-nowrap">
                          {fmtNum(bt.win_rate_pct, 1)}
                          {bt.win_rate_pct != null && "%"}
                        </td>
                        <td className="px-3 py-3 text-xs text-gray-500 whitespace-nowrap">
                          {fmtTime(bt.created_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}

function StatusBadge({ status }: { status: BacktestStatus }) {
  const styles: Record<BacktestStatus, string> = {
    pending: "bg-gray-100 text-gray-700",
    running: "bg-blue-50 text-blue-700",
    completed: "bg-green-50 text-green-700",
    failed: "bg-red-50 text-red-700",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs ${styles[status]}`}
    >
      {status}
    </span>
  );
}

function returnColor(v: number | null | undefined): string {
  if (v == null) return "text-gray-400";
  if (v > 0) return "text-green-700";
  if (v < 0) return "text-red-600";
  return "text-gray-700";
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return Number(v).toFixed(digits);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${Number(v).toFixed(4)}%`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString();
}

// ----- Sample-size helpers -----

function calcDaysTested(bt: BacktestSummary): number | null {
  if (!bt.bars_start || !bt.bars_end) return null;
  const start = new Date(bt.bars_start).getTime();
  const end = new Date(bt.bars_end).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    return null;
  }
  return (end - start) / (1000 * 60 * 60 * 24);
}

function fmtDaysCompact(d: number): string {
  if (d < 1) return `${(d * 24).toFixed(1)}h`;
  if (d < 60) return `${d.toFixed(1)}d`;
  if (d < 365) return `${(d / 30).toFixed(1)}mo`;
  return `${(d / 365).toFixed(1)}y`;
}

function sampleSizeColor(days: number | null): string {
  if (days == null) return "text-gray-400";
  if (days < 7) return "text-red-700 font-semibold";
  if (days < 30) return "text-amber-700 font-semibold";
  if (days < 90) return "text-gray-700";
  return "text-green-700";
}

function sampleSizeTooltip(days: number): string {
  if (days < 7) {
    return `Only ${days.toFixed(1)} days of data — severely insufficient sample.`;
  }
  if (days < 30) {
    return `${days.toFixed(1)} days — short window, results likely noise.`;
  }
  if (days < 90) {
    return `${days.toFixed(1)} days — limited window, sanity check only.`;
  }
  return `${days.toFixed(1)} days — reasonable backtest window.`;
}
