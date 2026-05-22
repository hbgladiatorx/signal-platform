"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import type {
  Instrument,
  LatestQuoteResponse,
  TradeEvent,
} from "@/lib/types";

export default function InstrumentDetailPage() {
  const params = useParams<{ symbol: string }>();
  const symbol = decodeURIComponent(params.symbol);
  const api = useApi();

  const instrumentQuery = useQuery({
    queryKey: ["instrument", symbol],
    queryFn: () =>
      api.get<Instrument>(`/instruments/${encodeURIComponent(symbol)}`),
  });

  const quoteQuery = useQuery({
    queryKey: ["quote", "latest", symbol],
    queryFn: () =>
      api.get<LatestQuoteResponse>(
        `/market/quote/latest?symbol=${encodeURIComponent(symbol)}`,
      ),
    refetchInterval: 5_000,
  });

  const tradesQuery = useQuery({
    queryKey: ["trades", symbol],
    queryFn: () =>
      api.get<TradeEvent[]>(
        `/market/trades?symbol=${encodeURIComponent(symbol)}&limit=20`,
      ),
    refetchInterval: 10_000,
  });

  return (
    <AppShell title={symbol}>
      <div className="space-y-6">
        {instrumentQuery.data && (
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <h2 className="text-base font-semibold text-navy-700">
              {instrumentQuery.data.canonical_symbol}
            </h2>
            <div className="mt-3 grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
              <Field
                label="Asset class"
                value={instrumentQuery.data.asset_class}
              />
              <Field label="Venue" value={instrumentQuery.data.venue} />
              <Field label="Base" value={instrumentQuery.data.base ?? "—"} />
              <Field label="Quote" value={instrumentQuery.data.quote ?? "—"} />
            </div>
          </div>
        )}

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="text-sm font-medium uppercase tracking-wide text-gray-500">
            Latest quote
          </h3>
          {quoteQuery.data ? (
            <div className="mt-3 grid grid-cols-2 gap-4 text-sm md:grid-cols-5">
              <Field label="Bid" value={quoteQuery.data.bid ?? "—"} />
              <Field label="Ask" value={quoteQuery.data.ask ?? "—"} />
              <Field label="Mid" value={quoteQuery.data.mid ?? "—"} />
              <Field label="Spread" value={quoteQuery.data.spread ?? "—"} />
              <Field
                label="Spread (bps)"
                value={
                  quoteQuery.data.spread_bps
                    ? Number(quoteQuery.data.spread_bps).toFixed(2)
                    : "—"
                }
              />
            </div>
          ) : (
            <div className="mt-3 text-sm text-gray-500">
              {quoteQuery.isLoading ? "Loading…" : "No quote available."}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-6 py-3">
            <h3 className="text-sm font-medium uppercase tracking-wide text-gray-500">
              Recent trades
            </h3>
          </div>
          {tradesQuery.data && tradesQuery.data.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-6 py-2 font-medium">Time (UTC)</th>
                  <th className="px-6 py-2 font-medium">Price</th>
                  <th className="px-6 py-2 font-medium">Quantity</th>
                  <th className="px-6 py-2 font-medium">Side</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {tradesQuery.data.map((trade) => (
                  <tr key={trade.venue_trade_id}>
                    <td className="px-6 py-2 font-mono text-xs text-gray-600">
                      {new Date(trade.ts).toISOString().replace("T", " ").slice(0, 19)}
                    </td>
                    <td className="px-6 py-2 font-mono">{trade.price}</td>
                    <td className="px-6 py-2 font-mono">{trade.quantity}</td>
                    <td className="px-6 py-2">
                      {trade.side === "b" ? (
                        <span className="text-green-600">buy</span>
                      ) : trade.side === "s" ? (
                        <span className="text-red-600">sell</span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="px-6 py-8 text-center text-sm text-gray-500">
              {tradesQuery.isLoading ? "Loading…" : "No recent trades."}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div className="mt-1 font-mono text-sm text-gray-800">{value}</div>
    </div>
  );
}
