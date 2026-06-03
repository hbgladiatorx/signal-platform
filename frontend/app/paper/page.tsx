"use client";

// frontend/app/paper/page.tsx
// List of live paper-trading sessions. Auto-refreshes while any are active.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import {
  KillSwitchState,
  PaperSessionSummary,
  fmtDateTime,
  fmtMoney,
  isActive,
  modeBadge,
  statusColor,
} from "@/lib/paper-types";

export default function PaperListPage() {
  const api = useApi();
  const router = useRouter();
  const qc = useQueryClient();

  const killswitch = useQuery({
    queryKey: ["live-killswitch"],
    queryFn: () => api.get<KillSwitchState>("/live/killswitch"),
    refetchInterval: 5000,
  });
  const engaged = killswitch.data?.engaged ?? false;
  const toggleKill = useMutation({
    mutationFn: (next: boolean) =>
      next
        ? api.post<KillSwitchState>("/live/killswitch", {})
        : api.delete<KillSwitchState>("/live/killswitch"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["live-killswitch"] }),
  });

  const { data, isLoading, error } = useQuery({
    queryKey: ["paper-sessions"],
    queryFn: () => api.get<PaperSessionSummary[]>("/paper-sessions"),
    refetchInterval: (q) => {
      const rows = q.state.data as PaperSessionSummary[] | undefined;
      if (!rows) return false;
      return rows.some((r) => isActive(r.status)) ? 3000 : false;
    },
  });

  return (
    <AppShell title="Paper Trading">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-navy-700">
              Live paper-trading sessions
            </h2>
            <p className="mt-1 text-xs text-gray-500 max-w-2xl">
              Run a strategy live against real market bars, routing orders to
              your Alpaca <strong>paper</strong> account. Auto-refreshes every 3
              seconds while sessions are active.
            </p>
          </div>
          <Link
            href="/paper/new"
            className="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 font-medium text-sm whitespace-nowrap"
          >
            + New Session
          </Link>
        </div>

        {/* Global live-trading kill-switch (affects real-money sessions only). */}
        <div
          className={`flex items-center justify-between rounded-md border p-3 text-sm ${
            engaged
              ? "bg-red-50 border-red-300 text-red-900"
              : "bg-gray-50 border-gray-200 text-gray-700"
          }`}
        >
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full ${
                engaged ? "bg-red-600" : "bg-emerald-500"
              }`}
            />
            <span>
              <strong>Live kill-switch:</strong>{" "}
              {engaged
                ? "ENGAGED — all real-money order submission is halted."
                : "off — live sessions can submit orders."}
            </span>
          </div>
          <button
            type="button"
            onClick={() => toggleKill.mutate(!engaged)}
            disabled={toggleKill.isPending || killswitch.isLoading}
            className={`px-3 py-1.5 rounded-md text-xs font-medium text-white disabled:opacity-50 ${
              engaged
                ? "bg-emerald-600 hover:bg-emerald-700"
                : "bg-red-600 hover:bg-red-700"
            }`}
          >
            {engaged ? "Disengage" : "Engage kill-switch"}
          </button>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-800 p-4 rounded-md text-sm">
            Error loading sessions: {(error as Error).message}
          </div>
        )}

        {isLoading && (
          <div className="text-gray-500 py-8 text-center">Loading…</div>
        )}

        {data && data.length === 0 && (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
            <p className="text-gray-700 font-medium mb-2">
              No paper sessions yet
            </p>
            <p className="text-gray-500 text-sm mb-4 max-w-xl mx-auto">
              Save an Alpaca paper API key in Settings, then start a session to
              trade one of your strategies live against real bars — with
              simulated fills from Alpaca.
            </p>
            <Link
              href="/paper/new"
              className="inline-block px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 text-sm"
            >
              Start your first
            </Link>
          </div>
        )}

        {data && data.length > 0 && (
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-700">Strategy</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-700">Mode</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-700">Symbols</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-700">Asset</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-700">Status</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Equity</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Realized P&amp;L</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Orders</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Fills</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.map((s) => (
                  <tr
                    key={s.id}
                    onClick={() => router.push(`/paper/${s.id}`)}
                    className="hover:bg-gray-50 cursor-pointer"
                  >
                    <td className="px-4 py-3 font-medium text-gray-900">{s.strategy_name}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 text-xs font-semibold rounded border ${modeBadge(s.mode).cls}`}>
                        {modeBadge(s.mode).label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 font-mono text-xs">{s.symbols.join(", ")}</td>
                    <td className="px-4 py-3 text-gray-600">{s.asset_class}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 text-xs font-medium rounded border ${statusColor(s.status)}`}>
                        {s.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-gray-900">{fmtMoney(s.current_equity)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      <span className={Number(s.realized_pnl) >= 0 ? "text-emerald-700" : "text-red-700"}>
                        {fmtMoney(s.realized_pnl)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-gray-700">{s.num_orders}</td>
                    <td className="px-4 py-3 text-right tabular-nums text-gray-700">{s.num_fills}</td>
                    <td className="px-4 py-3 text-right text-gray-500 text-xs whitespace-nowrap">{fmtDateTime(s.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="text-xs text-gray-500 leading-relaxed max-w-3xl">
          <strong className="text-gray-700">Two modes.</strong>{" "}
          <span className="text-gray-600">paper</span> sessions route to
          Alpaca&apos;s paper endpoint (no real money).{" "}
          <span className="text-red-700 font-medium">LIVE</span> sessions trade
          real funds on Binance.US spot. Live submission is gated by the global
          kill-switch above and each session&apos;s daily-loss halt. Educational
          use only — not investment advice.
        </div>
      </div>
    </AppShell>
  );
}
