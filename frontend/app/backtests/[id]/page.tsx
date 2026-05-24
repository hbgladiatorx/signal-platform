"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ColorType,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { AppShell } from "@/components/nav/AppShell";
import type {
  BacktestDetail,
  BacktestEquityPoint,
  BacktestStatus,
  BacktestTrade,
} from "@/lib/backtest-types";
import { useApi } from "@/lib/useApi";


// ============================================================
// Page
// ============================================================
export default function BacktestDetailPage() {
  const params = useParams();
  const id = (params?.id as string) ?? "";
  const api = useApi();

  // Header poll: every 3s while pending/running, else stop
  const detailQuery = useQuery({
    queryKey: ["backtest", id],
    queryFn: () => api.get<BacktestDetail>(`/backtests/${id}`),
    refetchInterval: (q) => {
      const d = q.state.data as BacktestDetail | undefined;
      if (!d) return false;
      return d.status === "pending" || d.status === "running" ? 3000 : false;
    },
    enabled: id.length > 0,
  });

  const status = detailQuery.data?.status;
  const isDone = status === "completed" || status === "failed";

  // Only fetch trades + equity once the run has finished
  const tradesQuery = useQuery({
    queryKey: ["backtest", id, "trades"],
    queryFn: () => api.get<BacktestTrade[]>(`/backtests/${id}/trades`),
    enabled: id.length > 0 && status === "completed",
  });

  const equityQuery = useQuery({
    queryKey: ["backtest", id, "equity"],
    queryFn: () => api.get<BacktestEquityPoint[]>(`/backtests/${id}/equity`),
    enabled: id.length > 0 && status === "completed",
  });

  // -------- render branches --------
  if (detailQuery.isLoading) {
    return (
      <AppShell title="Backtest">
        <div className="rounded-lg border border-gray-200 bg-white px-6 py-12 text-center text-sm text-gray-500">
          Loading backtest…
        </div>
      </AppShell>
    );
  }

  if (detailQuery.error) {
    return (
      <AppShell title="Backtest">
        <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
          Failed to load backtest: {(detailQuery.error as Error).message}
        </div>
      </AppShell>
    );
  }

  const detail = detailQuery.data;
  if (!detail) return null;

  return (
    <AppShell title={`Backtest ${detail.strategy_name}`}>
      <div className="space-y-4">
        {/* Back link */}
        <div>
          <Link
            href="/backtests"
            className="text-xs text-navy-600 hover:underline"
          >
            ← All backtests
          </Link>
        </div>

        {/* ---------- HEADER CARD ---------- */}
        <HeaderCard detail={detail} />

        {/* ---------- STATUS-DEPENDENT BODY ---------- */}
        {status === "failed" && <FailedCard detail={detail} />}

        {(status === "pending" || status === "running") && (
          <div className="rounded-lg border border-blue-200 bg-blue-50 px-6 py-8 text-center text-sm text-blue-800">
            Backtest is{" "}
            <span className="font-semibold">{status}</span>. This page
            auto-refreshes every 3 seconds.
          </div>
        )}

        {status === "completed" && (
          <>
            <MetricsGrid detail={detail} />

            <EquityChartCard
              loading={equityQuery.isLoading}
              error={equityQuery.error as Error | null}
              data={equityQuery.data}
              startingCash={Number(detail.starting_cash)}
            />

            <TradesCard
              loading={tradesQuery.isLoading}
              error={tradesQuery.error as Error | null}
              data={tradesQuery.data}
            />

            <ConfigCard detail={detail} />
          </>
        )}
      </div>
    </AppShell>
  );
}


// ============================================================
// Header card
// ============================================================
function HeaderCard({ detail }: { detail: BacktestDetail }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-mono text-sm font-semibold text-navy-700">
              {detail.strategy_name}
            </h2>
            <p className="mt-0.5 break-all font-mono text-xs text-gray-500">
              {detail.id}
            </p>
          </div>
          <StatusBadge status={detail.status} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 px-6 py-4 text-sm sm:grid-cols-4">
        <Field label="Symbols" value={detail.symbols.join(", ")} mono />
        <Field label="Resolution" value={detail.bar_resolution} />
        <Field
          label="Bars window"
          value={
            detail.bars_start && detail.bars_end
              ? `${fmtDate(detail.bars_start)} → ${fmtDate(detail.bars_end)}`
              : "—"
          }
        />
        <Field
          label="Bars"
          value={detail.num_bars != null ? String(detail.num_bars) : "—"}
        />
        <Field label="Created" value={fmtTime(detail.created_at)} />
        <Field
          label="Completed"
          value={detail.completed_at ? fmtTime(detail.completed_at) : "—"}
        />
        <Field
          label="Duration"
          value={
            detail.duration_seconds != null
              ? `${detail.duration_seconds.toFixed(3)} s`
              : "—"
          }
        />
        <Field
          label="Starting cash"
          value={`$${Number(detail.starting_cash).toLocaleString()}`}
        />
      </div>
    </div>
  );
}


// ============================================================
// Failed card
// ============================================================
function FailedCard({ detail }: { detail: BacktestDetail }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50">
      <div className="border-b border-red-200 px-6 py-3">
        <h3 className="text-sm font-semibold text-red-800">
          Run failed
        </h3>
      </div>
      <div className="px-6 py-4">
        <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-xs text-red-900">
          {detail.error_message ?? "No error message recorded."}
        </pre>
      </div>
    </div>
  );
}


// ============================================================
// Metrics grid
// ============================================================
function MetricsGrid({ detail }: { detail: BacktestDetail }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-6">
      <MetricTile
        label="Total return"
        value={fmtPctRich(detail.total_return_pct)}
        tone={returnTone(detail.total_return_pct)}
      />
      <MetricTile
        label="Annualized"
        value={fmtPctRich(detail.annualized_return_pct)}
        tone={returnTone(detail.annualized_return_pct)}
      />
      <MetricTile
        label="Sharpe"
        value={fmtNum(detail.sharpe_ratio, 2)}
      />
      <MetricTile
        label="Sortino"
        value={fmtNum(detail.sortino_ratio, 2)}
      />
      <MetricTile
        label="Max drawdown"
        value={fmtPctRich(detail.max_drawdown_pct)}
        tone="negative"
      />
      <MetricTile
        label="Calmar"
        value={fmtNum(detail.calmar_ratio, 2)}
      />
      <MetricTile
        label="Closed trades"
        value={fmtInt(detail.num_closed_trades)}
      />
      <MetricTile
        label="Open trades"
        value={fmtInt(detail.num_open_trades)}
      />
      <MetricTile
        label="Win rate"
        value={detail.win_rate_pct != null ? `${detail.win_rate_pct.toFixed(1)}%` : "—"}
      />
      <MetricTile
        label="Profit factor"
        value={fmtNum(detail.profit_factor, 2)}
      />
    </div>
  );
}

function MetricTile({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative" | "neutral";
}) {
  const valueClass =
    tone === "positive"
      ? "text-green-700"
      : tone === "negative"
        ? "text-red-700"
        : "text-navy-700";
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-gray-500">
        {label}
      </p>
      <p className={`mt-1 font-mono text-lg font-semibold ${valueClass}`}>
        {value}
      </p>
    </div>
  );
}


// ============================================================
// Equity curve chart
// ============================================================
function EquityChartCard({
  loading,
  error,
  data,
  startingCash,
}: {
  loading: boolean;
  error: Error | null;
  data: BacktestEquityPoint[] | undefined;
  startingCash: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current || !data || data.length === 0) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 360,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#374151",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: "#f3f4f6" },
        horzLines: { color: "#f3f4f6" },
      },
      rightPriceScale: { borderColor: "#e5e7eb" },
      timeScale: {
        borderColor: "#e5e7eb",
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: { mode: 1 },
    });
    chartRef.current = chart;

    const series = chart.addLineSeries({
      color: "#1E2761",
      lineWidth: 2,
      priceFormat: {
        type: "price",
        precision: 2,
        minMove: 0.01,
      },
    });
    seriesRef.current = series;

    series.setData(
      data.map((p) => ({
        time: Math.floor(new Date(p.ts).getTime() / 1000) as UTCTimestamp,
        value: Number(p.total_equity),
      })),
    );

    // Reference line at starting cash
    series.createPriceLine({
      price: startingCash,
      color: "#9ca3af",
      lineStyle: LineStyle.Dashed,
      lineWidth: 1,
      axisLabelVisible: true,
      title: "Start",
    });

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    const ro = new ResizeObserver(handleResize);
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [data, startingCash]);

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-6 py-3">
        <h3 className="text-sm font-semibold text-navy-700">
          Equity curve
        </h3>
        <p className="mt-0.5 text-xs text-gray-500">
          Total portfolio equity (cash + mark-to-market positions) at each
          bar close.
        </p>
      </div>
      <div className="px-6 py-4">
        {loading && (
          <div className="py-12 text-center text-sm text-gray-500">
            Loading equity curve…
          </div>
        )}
        {error && (
          <div className="py-4 text-center text-sm text-red-600">
            {error.message}
          </div>
        )}
        {data && data.length === 0 && (
          <div className="py-12 text-center text-sm text-gray-500">
            No equity points were recorded.
          </div>
        )}
        {data && data.length > 0 && (
          <div ref={containerRef} className="h-[360px] w-full" />
        )}
      </div>
    </div>
  );
}


// ============================================================
// Trades table
// ============================================================
function TradesCard({
  loading,
  error,
  data,
}: {
  loading: boolean;
  error: Error | null;
  data: BacktestTrade[] | undefined;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-6 py-3">
        <h3 className="text-sm font-semibold text-navy-700">
          Closed trades {data ? `(${data.length})` : ""}
        </h3>
        <p className="mt-0.5 text-xs text-gray-500">
          Round trips paired by position-zero segmentation. Open positions
          at the end of the run are not listed here.
        </p>
      </div>

      {loading && (
        <div className="px-6 py-12 text-center text-sm text-gray-500">
          Loading trades…
        </div>
      )}
      {error && (
        <div className="px-6 py-4 text-sm text-red-600">{error.message}</div>
      )}
      {data && data.length === 0 && (
        <div className="px-6 py-12 text-center text-sm text-gray-500">
          No closed trades. Either the strategy never opened a round trip,
          or the only positions are still open at the end of the data
          window.
        </div>
      )}
      {data && data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2 font-medium">#</th>
                <th className="px-3 py-2 font-medium">Symbol</th>
                <th className="px-3 py-2 font-medium">Side</th>
                <th className="px-3 py-2 font-medium whitespace-nowrap">
                  Entry
                </th>
                <th className="px-3 py-2 font-medium whitespace-nowrap">
                  Exit
                </th>
                <th className="px-3 py-2 text-right font-medium">Qty</th>
                <th className="px-3 py-2 text-right font-medium">
                  Entry $
                </th>
                <th className="px-3 py-2 text-right font-medium">Exit $</th>
                <th className="px-3 py-2 text-right font-medium">Gross</th>
                <th className="px-3 py-2 text-right font-medium">Fees</th>
                <th className="px-3 py-2 text-right font-medium">Net P&L</th>
                <th className="px-3 py-2 text-right font-medium">Dur.</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.map((t, i) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-3 py-2 text-xs text-gray-500">
                    {i + 1}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{t.symbol}</td>
                  <td className="px-3 py-2 text-xs">
                    <span
                      className={
                        t.side === "long"
                          ? "rounded bg-green-50 px-1.5 py-0.5 text-xs text-green-700"
                          : "rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-700"
                      }
                    >
                      {t.side}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap">
                    {fmtTime(t.entry_ts)}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap">
                    {fmtTime(t.exit_ts)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">
                    {fmtNumberStr(t.quantity, 6)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">
                    {fmtNumberStr(t.entry_avg_price, 2)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">
                    {fmtNumberStr(t.exit_avg_price, 2)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-mono text-xs ${pnlColor(t.gross_pnl)}`}
                  >
                    {fmtNumberStr(t.gross_pnl, 4)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-gray-600">
                    {fmtNumberStr(t.fees, 4)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-mono text-xs ${pnlColor(t.net_pnl)}`}
                  >
                    {fmtNumberStr(t.net_pnl, 4)}
                  </td>
                  <td className="px-3 py-2 text-right text-xs text-gray-500 whitespace-nowrap">
                    {fmtDuration(t.duration_seconds)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


// ============================================================
// Config card (params + execution knobs)
// ============================================================
function ConfigCard({ detail }: { detail: BacktestDetail }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-6 py-3">
        <h3 className="text-sm font-semibold text-navy-700">Configuration</h3>
      </div>
      <div className="grid grid-cols-1 gap-6 px-6 py-4 md:grid-cols-2">
        <div>
          <p className="mb-2 text-xs uppercase tracking-wide text-gray-500">
            Strategy parameters
          </p>
          <pre className="overflow-x-auto rounded bg-gray-50 p-3 font-mono text-xs text-gray-700">
            {JSON.stringify(detail.params_json, null, 2)}
          </pre>
        </div>
        <div>
          <p className="mb-2 text-xs uppercase tracking-wide text-gray-500">
            Execution config
          </p>
          <dl className="space-y-1 text-sm">
            <Row k="Starting cash">${Number(detail.starting_cash).toLocaleString()}</Row>
            <Row k="Fee rate">{detail.fee_rate_bps} bps ({(detail.fee_rate_bps / 100).toFixed(2)}%)</Row>
            <Row k="Slippage">{detail.slippage_bps} bps ({(detail.slippage_bps / 100).toFixed(2)}%)</Row>
          </dl>
        </div>
      </div>
    </div>
  );
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-gray-500">{k}</dt>
      <dd className="font-mono text-gray-700">{children}</dd>
    </div>
  );
}


// ============================================================
// Subcomponents and helpers
// ============================================================
function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`mt-0.5 text-sm text-gray-800 ${mono ? "font-mono" : ""}`}>
        {value}
      </p>
    </div>
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
    <span className={`rounded-full px-2 py-0.5 text-xs ${styles[status]}`}>
      {status}
    </span>
  );
}

function returnTone(v: number | null | undefined): "positive" | "negative" | "neutral" {
  if (v == null) return "neutral";
  if (v > 0) return "positive";
  if (v < 0) return "negative";
  return "neutral";
}

function pnlColor(v: number | string | null | undefined): string {
  const n = v == null ? null : Number(v);
  if (n == null || Number.isNaN(n)) return "text-gray-600";
  if (n > 0) return "text-green-700";
  if (n < 0) return "text-red-700";
  return "text-gray-700";
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return Number(v).toFixed(digits);
}

function fmtInt(v: number | null | undefined): string {
  if (v == null) return "—";
  return String(v);
}

function fmtPctRich(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${Number(v).toFixed(4)}%`;
}

function fmtNumberStr(v: number | string, digits: number): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toFixed(digits);
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString();
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}
