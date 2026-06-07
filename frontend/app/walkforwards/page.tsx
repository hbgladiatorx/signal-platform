"use client";

// frontend/app/walkforwards/page.tsx
// List view of walk-forward analyses. Uses TanStack Query with auto-refresh
// while any jobs are pending or running.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import {
  WalkforwardSummary,
  statusColor,
  overfitBadge,
  fmtSharpe,
  fmtPct,
  fmtDuration,
  fmtDateTime,
} from "@/lib/walkforward-types";

export default function WalkforwardsListPage() {
  const api = useApi();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete<void>(`/walkforwards/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["walkforwards"] });
      setConfirmId(null);
    },
  });

  const { data, isLoading, error } = useQuery({
    queryKey: ["walkforwards"],
    queryFn: () => api.get<WalkforwardSummary[]>("/walkforwards"),
    refetchInterval: (q) => {
      const rows = q.state.data as WalkforwardSummary[] | undefined;
      if (!rows) return false;
      const hasActive = rows.some(
        (r) => r.status === "pending" || r.status === "running",
      );
      return hasActive ? 3000 : false;
    },
  });

  return (
    <AppShell title="Walk-Forwards">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-navy-700">
              Your walk-forward analyses
            </h2>
            <p className="mt-1 text-xs text-gray-500 max-w-2xl">
              Rolling train/test parameter optimization. Surfaces overfitting
              that single-window backtests miss. Auto-refreshes every 3
              seconds while runs are active.
            </p>
          </div>
          <Link
            href="/walkforwards/new"
            className="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 font-medium text-sm whitespace-nowrap"
          >
            + New Walk-Forward
          </Link>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-800 p-4 rounded-md text-sm">
            Error loading walk-forwards: {(error as Error).message}
          </div>
        )}

        {isLoading && (
          <div className="text-gray-500 py-8 text-center">Loading…</div>
        )}

        {data && data.length === 0 && (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
            <p className="text-gray-700 font-medium mb-2">
              No walk-forwards yet
            </p>
            <p className="text-gray-500 text-sm mb-4 max-w-xl mx-auto">
              A walk-forward sweeps your parameter grid on a training window,
              picks the best combo, then evaluates it on a held-out test
              segment — repeated across rolling windows. The result is an
              out-of-sample-honest estimate of strategy performance.
            </p>
            <Link
              href="/walkforwards/new"
              className="inline-block px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 text-sm"
            >
              Create your first
            </Link>
          </div>
        )}

        {data && data.length > 0 && (
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-700">
                    Strategy
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-700">
                    Symbol
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-700">
                    Windows
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-700">
                    Status
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">
                    Train Sharpe
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">
                    Test Sharpe
                  </th>
                  <th className="px-4 py-3 text-center font-medium text-gray-700">
                    Overfit
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">
                    Win Rate
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">
                    Runtime
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">
                    Created
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.map((wf) => {
                  const overfit = overfitBadge(wf.overfit_drop);
                  return (
                    <tr
                      key={wf.id}
                      onClick={() => router.push(`/walkforwards/${wf.id}`)}
                      className="hover:bg-gray-50 cursor-pointer"
                    >
                      <td className="px-4 py-3 font-medium text-gray-900">
                        {wf.strategy_name}
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {wf.symbols.join(", ")}
                      </td>
                      <td className="px-4 py-3 text-gray-600 tabular-nums">
                        {wf.num_windows}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block px-2 py-0.5 text-xs font-medium rounded border ${statusColor(wf.status)}`}
                        >
                          {wf.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-900">
                        {fmtSharpe(wf.avg_train_sharpe)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        <span
                          className={
                            wf.avg_test_sharpe === null
                              ? "text-gray-400"
                              : wf.avg_test_sharpe > 0
                                ? "text-emerald-700 font-medium"
                                : "text-red-700 font-medium"
                          }
                        >
                          {fmtSharpe(wf.avg_test_sharpe)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span
                          className={`inline-block px-2 py-0.5 text-xs font-medium rounded border ${overfit.color}`}
                          title={overfit.description}
                        >
                          {overfit.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                        {fmtPct(wf.win_rate_windows_pct, 0)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-600">
                        {fmtDuration(wf.duration_seconds)}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-500 text-xs whitespace-nowrap">
                        {fmtDateTime(wf.created_at)}
                      </td>
                      <td
                        className="px-4 py-3 text-right whitespace-nowrap"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {confirmId === wf.id ? (
                          <span className="inline-flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => deleteMutation.mutate(wf.id)}
                              disabled={deleteMutation.isPending}
                              className="text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
                            >
                              {deleteMutation.isPending ? "…" : "Confirm"}
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmId(null)}
                              className="text-xs text-gray-500 hover:text-gray-700"
                            >
                              Cancel
                            </button>
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setConfirmId(wf.id)}
                            className="text-xs text-gray-500 hover:text-red-600"
                          >
                            Delete
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="text-xs text-gray-500 leading-relaxed max-w-3xl">
          <strong className="text-gray-700">Educational use only.</strong>{" "}
          Walk-forward analysis is a diagnostic for overfit risk, not a
          guarantee of future performance. Out-of-sample windows are still
          historical. Trading carries substantial risk; you can lose your
          entire investment.
        </div>
      </div>
    </AppShell>
  );
}
