"use client";

// frontend/app/walkforwards/[id]/page.tsx
// Detail view: summary cards, per-window cards, dense table.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import {
  WalkforwardDetail,
  WindowResult,
  statusColor,
  overfitBadge,
  fmtSharpe,
  fmtPct,
  fmtDuration,
  fmtNum,
  fmtDate,
  fmtDateTime,
} from "@/lib/walkforward-types";

export default function WalkforwardDetailPage() {
  const api = useApi();
  const params = useParams();
  const id = String(params?.id ?? "");
  const router = useRouter();
  const queryClient = useQueryClient();
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const deleteMutation = useMutation({
    mutationFn: () => api.delete<void>(`/walkforwards/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["walkforwards"] });
      router.push("/walkforwards");
    },
  });

  const {
    data: wf,
    error,
    isLoading,
  } = useQuery({
    queryKey: ["walkforward", id],
    queryFn: () => api.get<WalkforwardDetail>(`/walkforwards/${id}`),
    enabled: !!id,
    refetchInterval: (q) => {
      const w = q.state.data as WalkforwardDetail | undefined;
      if (!w) return false;
      return w.status === "pending" || w.status === "running" ? 2000 : false;
    },
  });

  if (error) {
    return (
      <AppShell title="Walk-Forward">
        <div className="bg-red-50 border border-red-200 text-red-800 p-4 rounded-md">
          Error loading walk-forward: {(error as Error).message}
        </div>
      </AppShell>
    );
  }

  if (isLoading || !wf) {
    return (
      <AppShell title="Walk-Forward">
        <div className="text-gray-500 py-8">Loading…</div>
      </AppShell>
    );
  }

  const overfit = overfitBadge(wf.overfit_drop);
  const windows = wf.windows_result ?? [];

  return (
    <AppShell title={`Walk-Forward: ${wf.strategy_name}`}>
      <div className="space-y-4">
        {/* Header */}
        <div>
          <div className="flex items-center justify-between gap-3">
            <Link
              href="/walkforwards"
              className="text-sm text-indigo-600 hover:underline"
            >
              ← Walk-Forwards
            </Link>
            {confirmingDelete ? (
              <span className="inline-flex items-center gap-2">
                <span className="text-xs text-gray-500">Delete this run?</span>
                <button
                  type="button"
                  onClick={() => deleteMutation.mutate()}
                  disabled={deleteMutation.isPending}
                  className="text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
                >
                  {deleteMutation.isPending ? "Deleting…" : "Delete"}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmingDelete(false)}
                  disabled={deleteMutation.isPending}
                  className="text-xs text-gray-500 hover:text-gray-700"
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmingDelete(true)}
                className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:border-red-300 hover:text-red-600"
              >
                Delete
              </button>
            )}
          </div>
          {deleteMutation.isError && (
            <div className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              Failed to delete: {(deleteMutation.error as Error).message}
            </div>
          )}
          <div className="flex items-center gap-3 flex-wrap mt-2">
            <h2 className="text-base font-semibold text-navy-700">
              {wf.strategy_name}
            </h2>
            <span
              className={`inline-block px-2 py-0.5 text-xs font-medium rounded border ${statusColor(wf.status)}`}
            >
              {wf.status}
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            <span className="font-mono">{wf.symbols.join(", ")}</span>
            {" · "}
            <span className="font-mono">{wf.bar_resolution}</span>
            {" · "}
            {wf.num_windows} windows
            {" · "}
            train {wf.train_bars} / test {wf.test_bars} bars
            {" · "}
            selected by {wf.selection_metric}
          </p>
          <p className="text-xs text-gray-500 mt-1">
            Started {wf.started_at ? fmtDateTime(wf.started_at) : "—"}
            {" · "}
            Finished {wf.completed_at ? fmtDateTime(wf.completed_at) : "—"}
            {" · "}
            Runtime {fmtDuration(wf.duration_seconds)}
            {" · "}
            {fmtNum(wf.total_backtests_run)} backtests run
          </p>
        </div>

        {wf.error_message && (
          <div className="bg-red-50 border border-red-200 rounded-md p-4">
            <h3 className="text-sm font-semibold text-red-900 mb-2">
              Run failed
            </h3>
            <pre className="text-xs text-red-800 whitespace-pre-wrap overflow-x-auto max-h-64 font-mono">
              {wf.error_message}
            </pre>
          </div>
        )}

        {/* Summary cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <SummaryCard
            label="Avg Train Sharpe"
            value={fmtSharpe(wf.avg_train_sharpe)}
            hint="In-sample (param-selection bias)"
            tone="neutral"
          />
          <SummaryCard
            label="Avg Test Sharpe"
            value={fmtSharpe(wf.avg_test_sharpe)}
            hint="Out-of-sample (honest estimate)"
            tone={
              wf.avg_test_sharpe === null
                ? "neutral"
                : wf.avg_test_sharpe > 0
                  ? "good"
                  : "bad"
            }
          />
          <SummaryCard
            label="Overfit Drop"
            value={fmtSharpe(wf.overfit_drop)}
            hint={overfit.description}
            tone={
              wf.overfit_drop === null
                ? "neutral"
                : wf.overfit_drop > 1
                  ? "bad"
                  : wf.overfit_drop > 0
                    ? "warn"
                    : "good"
            }
            badge={overfit.label}
          />
          <SummaryCard
            label="Test Win Rate"
            value={fmtPct(wf.win_rate_windows_pct, 0)}
            hint="% of test windows with return > 0"
            tone={
              wf.win_rate_windows_pct === null
                ? "neutral"
                : wf.win_rate_windows_pct >= 50
                  ? "good"
                  : "bad"
            }
          />
        </div>

        {/* Param grid */}
        <section className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-navy-700 mb-3">
            Parameter Grid
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
            {Object.entries(wf.param_grid).map(([k, vs]) => (
              <div
                key={k}
                className="flex items-baseline gap-2 font-mono text-xs"
              >
                <span className="text-gray-500">{k}:</span>
                <span className="text-gray-900">
                  [{(vs as unknown[]).map((v) => String(v)).join(", ")}]
                </span>
              </div>
            ))}
          </div>
          <div className="mt-3 text-xs text-gray-500">
            {wf.total_combos ?? "?"} combo
            {wf.total_combos === 1 ? "" : "s"} × {wf.num_windows} windows ={" "}
            {fmtNum(wf.total_backtests_run)} total backtests
          </div>
        </section>

        {/* Per-window cards */}
        {windows.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-navy-700 mb-3">
              Per-Window Results
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {windows.map((w) => (
                <WindowCard key={w.window_index} window={w} />
              ))}
            </div>
          </section>
        )}

        {/* Dense table */}
        {windows.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-navy-700 mb-3">
              Per-Window Table
            </h3>
            <div className="bg-white border border-gray-200 rounded-lg overflow-x-auto shadow-sm">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-gray-700">
                      #
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-700">
                      Train Range
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-700">
                      Test Range
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-700">
                      Best Params
                    </th>
                    <th className="px-3 py-2 text-right font-medium text-gray-700">
                      Train Sharpe
                    </th>
                    <th className="px-3 py-2 text-right font-medium text-gray-700">
                      Test Sharpe
                    </th>
                    <th className="px-3 py-2 text-right font-medium text-gray-700">
                      Test Return
                    </th>
                    <th className="px-3 py-2 text-right font-medium text-gray-700">
                      Test MaxDD
                    </th>
                    <th className="px-3 py-2 text-right font-medium text-gray-700">
                      Test Trades
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {windows.map((w) => (
                    <tr key={w.window_index} className="hover:bg-gray-50">
                      <td className="px-3 py-2 text-gray-600 tabular-nums">
                        {w.window_index}
                      </td>
                      <td className="px-3 py-2 text-gray-700 text-xs whitespace-nowrap">
                        {fmtDate(w.train_start_ts)} →{" "}
                        {fmtDate(w.train_end_ts)}
                      </td>
                      <td className="px-3 py-2 text-gray-700 text-xs whitespace-nowrap">
                        {fmtDate(w.test_start_ts)} →{" "}
                        {fmtDate(w.test_end_ts)}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-gray-800">
                        {Object.entries(w.best_params)
                          .map(([k, v]) => `${k}=${v}`)
                          .join(", ")}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {fmtSharpe(w.train_sharpe)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        <span
                          className={
                            w.test_sharpe === null
                              ? "text-gray-400"
                              : w.test_sharpe > 0
                                ? "text-emerald-700 font-medium"
                                : "text-red-700 font-medium"
                          }
                        >
                          {fmtSharpe(w.test_sharpe)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        <span
                          className={
                            w.test_total_return_pct === null
                              ? "text-gray-400"
                              : w.test_total_return_pct > 0
                                ? "text-emerald-700"
                                : w.test_total_return_pct < 0
                                  ? "text-red-700"
                                  : "text-gray-600"
                          }
                        >
                          {fmtPct(w.test_total_return_pct)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                        {fmtPct(w.test_max_drawdown_pct)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                        {fmtNum(w.test_num_closed_trades)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <div className="bg-amber-50 border border-amber-200 rounded-md p-4">
          <h3 className="text-sm font-semibold text-amber-900 mb-2">
            Interpreting these results
          </h3>
          <ul className="text-xs text-amber-900 space-y-1 list-disc pl-5">
            <li>
              <strong>Train Sharpe</strong> is the best-of-N from a parameter
              sweep — the maximum of a sample distribution, so it&apos;s
              mechanically biased upward.
            </li>
            <li>
              <strong>Test Sharpe</strong> is computed on held-out bars after
              params were chosen — the honest out-of-sample estimate.
            </li>
            <li>
              <strong>Overfit drop</strong> = train Sharpe − test Sharpe.
              Drops above ~1.0 suggest the strategy fits noise rather than
              signal.
            </li>
            <li>
              Walk-forward is diagnostic, not predictive. Real markets are
              non-stationary; even strong OOS performance does not guarantee
              future returns.
            </li>
          </ul>
        </div>

        <div className="text-xs text-gray-500 leading-relaxed">
          <strong className="text-gray-700">Educational use only.</strong> All
          backtest results — including walk-forward — are based on historical
          data and do not predict future performance. Trading involves
          substantial risk; you may lose your entire investment.
        </div>
      </div>
    </AppShell>
  );
}

// ============================================================
// Sub-components
// ============================================================
type Tone = "neutral" | "good" | "warn" | "bad";

function toneClasses(tone: Tone): string {
  switch (tone) {
    case "good":
      return "border-emerald-200 bg-emerald-50";
    case "warn":
      return "border-amber-200 bg-amber-50";
    case "bad":
      return "border-red-200 bg-red-50";
    case "neutral":
      return "border-gray-200 bg-white";
  }
}

function toneValueColor(tone: Tone): string {
  switch (tone) {
    case "good":
      return "text-emerald-900";
    case "warn":
      return "text-amber-900";
    case "bad":
      return "text-red-900";
    case "neutral":
      return "text-gray-900";
  }
}

function SummaryCard({
  label,
  value,
  hint,
  tone,
  badge,
}: {
  label: string;
  value: string;
  hint: string;
  tone: Tone;
  badge?: string;
}) {
  return (
    <div
      className={`border rounded-lg p-4 shadow-sm ${toneClasses(tone)}`}
      title={hint}
    >
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs font-medium text-gray-600 uppercase tracking-wide">
          {label}
        </p>
        {badge && (
          <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-700">
            {badge}
          </span>
        )}
      </div>
      <p
        className={`text-2xl font-bold mt-2 tabular-nums ${toneValueColor(tone)}`}
      >
        {value}
      </p>
      <p className="text-[11px] text-gray-500 mt-1 leading-snug">{hint}</p>
    </div>
  );
}

function WindowCard({ window: w }: { window: WindowResult }) {
  const overfit =
    w.train_sharpe !== null && w.test_sharpe !== null
      ? w.train_sharpe - w.test_sharpe
      : null;
  const overfitInfo = overfitBadge(overfit);

  const testPositive =
    w.test_total_return_pct !== null && w.test_total_return_pct > 0;

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
      <div className="flex items-baseline justify-between mb-3">
        <h4 className="text-sm font-semibold text-navy-700">
          Window {w.window_index + 1}
        </h4>
        <span
          className={`inline-block px-2 py-0.5 text-[10px] font-medium rounded border ${overfitInfo.color}`}
          title={overfitInfo.description}
        >
          {overfitInfo.label}
        </span>
      </div>

      <div className="text-xs text-gray-500 mb-3 space-y-0.5">
        <div>
          <span className="text-gray-400">Train:</span>{" "}
          {fmtDate(w.train_start_ts)} → {fmtDate(w.train_end_ts)}
        </div>
        <div>
          <span className="text-gray-400">Test:</span>{" "}
          {fmtDate(w.test_start_ts)} → {fmtDate(w.test_end_ts)}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
        <div>
          <div className="text-gray-500 mb-1">Train Sharpe</div>
          <div className="text-base font-semibold text-gray-900 tabular-nums">
            {fmtSharpe(w.train_sharpe)}
          </div>
        </div>
        <div>
          <div className="text-gray-500 mb-1">Test Sharpe</div>
          <div
            className={`text-base font-semibold tabular-nums ${
              w.test_sharpe === null
                ? "text-gray-400"
                : w.test_sharpe > 0
                  ? "text-emerald-700"
                  : "text-red-700"
            }`}
          >
            {fmtSharpe(w.test_sharpe)}
          </div>
        </div>
        <div>
          <div className="text-gray-500 mb-1">Train Return</div>
          <div className="text-sm text-gray-900 tabular-nums">
            {fmtPct(w.train_total_return_pct)}
          </div>
        </div>
        <div>
          <div className="text-gray-500 mb-1">Test Return</div>
          <div
            className={`text-sm tabular-nums ${
              w.test_total_return_pct === null
                ? "text-gray-400"
                : testPositive
                  ? "text-emerald-700 font-medium"
                  : w.test_total_return_pct < 0
                    ? "text-red-700 font-medium"
                    : "text-gray-700"
            }`}
          >
            {fmtPct(w.test_total_return_pct)}
          </div>
        </div>
        <div>
          <div className="text-gray-500 mb-1">Train MaxDD</div>
          <div className="text-sm text-gray-700 tabular-nums">
            {fmtPct(w.train_max_drawdown_pct)}
          </div>
        </div>
        <div>
          <div className="text-gray-500 mb-1">Test MaxDD</div>
          <div className="text-sm text-gray-700 tabular-nums">
            {fmtPct(w.test_max_drawdown_pct)}
          </div>
        </div>
        <div>
          <div className="text-gray-500 mb-1">Train Trades</div>
          <div className="text-sm text-gray-700 tabular-nums">
            {fmtNum(w.train_num_closed_trades)}
          </div>
        </div>
        <div>
          <div className="text-gray-500 mb-1">Test Trades</div>
          <div className="text-sm text-gray-700 tabular-nums">
            {fmtNum(w.test_num_closed_trades)}
          </div>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-gray-100">
        <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
          Best Params
        </div>
        <div className="font-mono text-xs text-gray-800">
          {Object.entries(w.best_params)
            .map(([k, v]) => `${k}=${v}`)
            .join(", ") || "—"}
        </div>
      </div>
    </div>
  );
}
