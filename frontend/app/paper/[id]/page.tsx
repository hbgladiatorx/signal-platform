"use client";

// frontend/app/paper/[id]/page.tsx
// Live paper-session detail: status + controls, positions, orders, fills,
// and an equity curve. Auto-refreshes while the session is active.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import {
  PaperEquityPoint,
  PaperFill,
  PaperOrder,
  PaperPosition,
  PaperSessionDetail,
  fmtDateTime,
  fmtMoney,
  fmtQty,
  isActive,
  modeBadge,
  num,
  orderStatusColor,
  statusColor,
} from "@/lib/paper-types";

export default function PaperDetailPage() {
  const api = useApi();
  const params = useParams();
  const id = params.id as string;
  const qc = useQueryClient();

  const refetchInterval = (active: boolean | undefined) =>
    active ? 3000 : false;

  const session = useQuery({
    queryKey: ["paper-session", id],
    queryFn: () => api.get<PaperSessionDetail>(`/paper-sessions/${id}`),
    refetchInterval: (q) =>
      refetchInterval(
        q.state.data ? isActive((q.state.data as PaperSessionDetail).status) : true,
      ),
  });
  const active = session.data ? isActive(session.data.status) : false;

  const positions = useQuery({
    queryKey: ["paper-positions", id],
    queryFn: () => api.get<PaperPosition[]>(`/paper-sessions/${id}/positions`),
    refetchInterval: () => (active ? 3000 : false),
  });
  const orders = useQuery({
    queryKey: ["paper-orders", id],
    queryFn: () => api.get<PaperOrder[]>(`/paper-sessions/${id}/orders`),
    refetchInterval: () => (active ? 3000 : false),
  });
  const fills = useQuery({
    queryKey: ["paper-fills", id],
    queryFn: () => api.get<PaperFill[]>(`/paper-sessions/${id}/fills`),
    refetchInterval: () => (active ? 3000 : false),
  });
  const equity = useQuery({
    queryKey: ["paper-equity", id],
    queryFn: () => api.get<PaperEquityPoint[]>(`/paper-sessions/${id}/equity`),
    refetchInterval: () => (active ? 5000 : false),
  });

  const stopMutation = useMutation({
    mutationFn: () => api.post(`/paper-sessions/${id}/stop`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["paper-session", id] }),
  });
  const flattenMutation = useMutation({
    mutationFn: () => api.post(`/paper-sessions/${id}/flatten`, {}),
  });

  const s = session.data;

  return (
    <AppShell title="Paper Session">
      <div className="space-y-4 max-w-5xl">
        <div className="flex items-start justify-between">
          <div>
            <Link href="/paper" className="text-sm text-indigo-600 hover:underline">
              ← Paper Trading
            </Link>
            {s && (
              <div className="mt-2 flex items-center gap-3">
                <h2 className="text-base font-semibold text-navy-700">{s.strategy_name}</h2>
                <span className={`inline-block px-2 py-0.5 text-xs font-semibold rounded border ${modeBadge(s.mode).cls}`}>
                  {modeBadge(s.mode).label}
                </span>
                <span className={`inline-block px-2 py-0.5 text-xs font-medium rounded border ${statusColor(s.status)}`}>
                  {s.status}
                </span>
                <span className="text-xs text-gray-500 font-mono">{s.symbols.join(", ")}</span>
              </div>
            )}
          </div>
          {s && (
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => flattenMutation.mutate()}
                disabled={!active || flattenMutation.isPending}
                className="px-3 py-2 text-sm font-medium text-amber-700 border border-amber-300 rounded-md hover:bg-amber-50 disabled:opacity-40"
                title="Market-sell all open positions"
              >
                Flatten
              </button>
              <button
                type="button"
                onClick={() => stopMutation.mutate()}
                disabled={!active || stopMutation.isPending}
                className="px-3 py-2 text-sm font-medium text-white bg-red-600 rounded-md hover:bg-red-700 disabled:opacity-40"
              >
                {stopMutation.isPending ? "Stopping…" : "Stop"}
              </button>
            </div>
          )}
        </div>

        {session.error && (
          <div className="bg-red-50 border border-red-200 text-red-800 p-4 rounded-md text-sm">
            {(session.error as Error).message}
          </div>
        )}
        {s?.error_message && (
          <div className="bg-red-50 border border-red-200 text-red-800 p-4 rounded-md text-sm">
            <strong>Session error:</strong> {s.error_message}
          </div>
        )}

        {s?.mode === "live" && (
          <div className="bg-red-50 border border-red-300 text-red-900 p-3 rounded-md text-sm">
            <strong>Live — real money</strong> on Binance.US. Daily-loss halt:{" "}
            {s.max_daily_loss ? fmtMoney(s.max_daily_loss) : "—"}. The global
            kill-switch on the Paper Trading page halts all live submission.
          </div>
        )}

        {s && (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard label="Equity" value={fmtMoney(s.current_equity)} />
              <StatCard
                label="Realized P&L"
                value={fmtMoney(s.realized_pnl)}
                tone={(num(s.realized_pnl) ?? 0) >= 0 ? "pos" : "neg"}
              />
              <StatCard label="Orders" value={String(s.num_orders)} />
              <StatCard label="Fills" value={String(s.num_fills)} />
            </div>

            {/* Equity curve */}
            <section className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
              <h3 className="text-sm font-semibold text-navy-700 mb-3">Equity Curve</h3>
              <EquitySparkline points={equity.data ?? []} />
            </section>

            {/* Positions */}
            <Panel title="Open Positions">
              {(positions.data?.length ?? 0) === 0 ? (
                <Empty>No open positions.</Empty>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      <Th>Symbol</Th><Th right>Qty</Th><Th right>Avg Cost</Th><Th right>Realized P&L</Th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {positions.data!.map((p) => (
                      <tr key={p.symbol}>
                        <Td className="font-mono">{p.symbol}</Td>
                        <Td right>{fmtQty(p.quantity)}</Td>
                        <Td right>{fmtMoney(p.avg_cost)}</Td>
                        <Td right>{fmtMoney(p.realized_pnl)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>

            {/* Orders */}
            <Panel title="Orders">
              {(orders.data?.length ?? 0) === 0 ? (
                <Empty>No orders yet.</Empty>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      <Th>Time</Th><Th>Symbol</Th><Th>Side</Th><Th>Type</Th>
                      <Th right>Qty</Th><Th right>Filled</Th><Th right>Avg Fill</Th><Th>Status</Th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {orders.data!.map((o) => (
                      <tr key={o.id}>
                        <Td className="text-xs text-gray-500 whitespace-nowrap">{fmtDateTime(o.submitted_ts)}</Td>
                        <Td className="font-mono">{o.symbol}</Td>
                        <Td className={o.side === "buy" ? "text-emerald-700" : "text-red-700"}>{o.side}</Td>
                        <Td>{o.order_type}</Td>
                        <Td right>{fmtQty(o.quantity)}</Td>
                        <Td right>{fmtQty(o.filled_quantity)}</Td>
                        <Td right>{o.avg_fill_price ? fmtMoney(o.avg_fill_price) : "—"}</Td>
                        <Td>
                          <span className={`inline-block px-2 py-0.5 text-xs font-medium rounded border ${orderStatusColor(o.status)}`} title={o.error_message ?? undefined}>
                            {o.status}
                          </span>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>

            {/* Fills */}
            <Panel title="Fills">
              {(fills.data?.length ?? 0) === 0 ? (
                <Empty>No fills yet.</Empty>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      <Th>Time</Th><Th>Symbol</Th><Th>Side</Th><Th right>Qty</Th><Th right>Price</Th><Th right>Fee</Th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {fills.data!.map((f) => (
                      <tr key={f.id}>
                        <Td className="text-xs text-gray-500 whitespace-nowrap">{fmtDateTime(f.filled_ts)}</Td>
                        <Td className="font-mono">{f.symbol}</Td>
                        <Td className={f.side === "buy" ? "text-emerald-700" : "text-red-700"}>{f.side}</Td>
                        <Td right>{fmtQty(f.quantity)}</Td>
                        <Td right>{fmtMoney(f.price)}</Td>
                        <Td right>{fmtMoney(f.fee)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </>
        )}
      </div>
    </AppShell>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "pos" | "neg";
}) {
  const color =
    tone === "pos" ? "text-emerald-700" : tone === "neg" ? "text-red-700" : "text-gray-900";
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${color}`}>{value}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="bg-white border border-gray-200 rounded-lg overflow-hidden shadow-sm">
      <div className="px-5 py-3 border-b border-gray-200">
        <h3 className="text-sm font-semibold text-navy-700">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="px-5 py-6 text-sm text-gray-500 text-center">{children}</div>;
}

function Th({ children, right }: { children: ReactNode; right?: boolean }) {
  return (
    <th className={`px-4 py-2 font-medium text-gray-700 ${right ? "text-right" : "text-left"}`}>
      {children}
    </th>
  );
}

function Td({
  children,
  right,
  className,
}: {
  children: ReactNode;
  right?: boolean;
  className?: string;
}) {
  return (
    <td className={`px-4 py-2 ${right ? "text-right tabular-nums" : ""} ${className ?? ""}`}>
      {children}
    </td>
  );
}

/** Minimal inline SVG line chart for the equity curve (no extra deps). */
function EquitySparkline({ points }: { points: PaperEquityPoint[] }) {
  if (points.length < 2) {
    return <div className="text-sm text-gray-500 py-6 text-center">Collecting equity samples…</div>;
  }
  const values = points.map((p) => num(p.total_equity) ?? 0);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const W = 720;
  const H = 160;
  const stepX = W / (points.length - 1);
  const path = values
    .map((v, i) => {
      const x = i * stepX;
      const y = H - ((v - min) / range) * H;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  const stroke = up ? "#047857" : "#b91c1c";
  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: H }}>
        <path d={path} fill="none" stroke={stroke} strokeWidth={2} />
      </svg>
      <div className="flex justify-between text-xs text-gray-500 mt-1">
        <span>{fmtMoney(values[0])}</span>
        <span>{fmtMoney(values[values.length - 1])}</span>
      </div>
    </div>
  );
}
