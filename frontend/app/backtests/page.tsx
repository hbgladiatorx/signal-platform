"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { AppShell } from "@/components/nav/AppShell";
import type { BacktestStatus, BacktestSummary } from "@/lib/backtest-types";
import { useApi } from "@/lib/useApi";

export default function BacktestsListPage() {
  const api = useApi();

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
              Strategies run against historical data. Auto-refreshes every
              3 seconds while runs are active.
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
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-6 py-2 font-medium">Strategy</th>
                  <th className="px-6 py-2 font-medium">Symbols</th>
                  <th className="px-6 py-2 font-medium">Res.</th>
                  <th className="px-6 py-2 font-medium">Status</th>
                  <th className="px-6 py-2 text-right font-medium">Return</th>
                  <th className="px-6 py-2 text-right font-medium">Sharpe</th>
                  <th className="px-6 py-2 text-right font-medium">Max DD</th>
                  <th className="px-6 py-2 text-right font-medium">Trades</th>
                  <th className="px-6 py-2 text-right font-medium">Win %</th>
                  <th className="px-6 py-2 font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.map((bt) => (
                  <tr key={bt.id} className="hover:bg-gray-50">
                    <td className="px-6 py-3">
                      <Link
                        href={`/backtests/${bt.id}`}
                        className="font-mono text-xs text-navy-600 hover:underline"
                      >
                        {bt.strategy_name}
                      </Link>
                    </td>
                    <td className="px-6 py-3 font-mono text-xs text-gray-600">
                      {bt.symbols.join(", ")}
                    </td>
                    <td className="px-6 py-3 text-gray-600">
                      {bt.bar_resolution}
                    </td>
                    <td className="px-6 py-3">
                      <StatusBadge status={bt.status} />
                    </td>
                    <td
                      className={`px-6 py-3 text-right font-mono ${returnColor(bt.total_return_pct)}`}
                    >
                      {fmtPct(bt.total_return_pct)}
                    </td>
                    <td className="px-6 py-3 text-right font-mono text-gray-700">
                      {fmtNum(bt.sharpe_ratio, 2)}
                    </td>
                    <td className="px-6 py-3 text-right font-mono text-gray-700">
                      {fmtPct(bt.max_drawdown_pct)}
                    </td>
                    <td className="px-6 py-3 text-right font-mono text-gray-700">
                      {bt.num_closed_trades ?? "—"}
                    </td>
                    <td className="px-6 py-3 text-right font-mono text-gray-700">
                      {fmtNum(bt.win_rate_pct, 1)}
                      {bt.win_rate_pct != null && "%"}
                    </td>
                    <td className="px-6 py-3 text-xs text-gray-500">
                      {fmtTime(bt.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
