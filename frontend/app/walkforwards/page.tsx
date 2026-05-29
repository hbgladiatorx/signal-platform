"use client";

// frontend/app/walkforwards/page.tsx
// List view of walk-forward analyses. Polls the API every 3s if any jobs
// are pending or running so completion lands without a manual refresh.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  WalkforwardSummary,
  statusColor,
  overfitBadge,
  fmtSharpe,
  fmtPct,
  fmtDuration,
  fmtDateTime,
} from "@/lib/walkforward-types";
import { fetchAuthed, API_BASE } from "@/lib/api";

export default function WalkforwardsListPage() {
  const router = useRouter();
  const [items, setItems] = useState<WalkforwardSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let pollHandle: ReturnType<typeof setTimeout> | null = null;

    async function load() {
      try {
        const res = await fetchAuthed(`${API_BASE}/walkforwards`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: WalkforwardSummary[] = await res.json();
        if (!alive) return;
        setItems(data);
        setError(null);

        // Re-poll if anything is still running
        const inFlight = data.some(
          (d) => d.status === "pending" || d.status === "running",
        );
        if (inFlight) {
          pollHandle = setTimeout(load, 3000);
        }
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "Unknown error");
      }
    }

    load();
    return () => {
      alive = false;
      if (pollHandle) clearTimeout(pollHandle);
    };
  }, []);

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            Walk-Forward Analyses
          </h1>
          <p className="text-sm text-gray-600 mt-1 max-w-2xl">
            Rolling train/test parameter optimization. Surfaces overfitting that
            single-window backtests miss.
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
        <div className="bg-red-50 border border-red-200 text-red-800 p-4 rounded-md mb-4 text-sm">
          Error loading walk-forwards: {error}
        </div>
      )}

      {items === null && !error && (
        <div className="text-gray-500 py-8 text-center">Loading…</div>
      )}

      {items?.length === 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
          <p className="text-gray-700 font-medium mb-2">No walk-forwards yet</p>
          <p className="text-gray-500 text-sm mb-4 max-w-xl mx-auto">
            A walk-forward sweeps your parameter grid on a training window,
            picks the best combo, then evaluates it on a held-out test segment
            — repeated across rolling windows. The result is an
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

      {items && items.length > 0 && (
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
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((wf) => {
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
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-6 text-xs text-gray-500 leading-relaxed max-w-3xl">
        <strong className="text-gray-700">Educational use only.</strong>{" "}
        Walk-forward analysis is a diagnostic tool for overfit risk, not a
        guarantee of future performance. Out-of-sample windows are still
        historical and subject to regime change. Trading carries substantial
        risk; you can lose your entire investment.
      </div>
    </div>
  );
}
