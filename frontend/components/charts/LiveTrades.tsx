"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

export interface LiveTrade {
  ts: string;
  price: string;
  quantity: string;
  side: "b" | "s" | null;
  venue_trade_id: string;
}

interface LiveTradesProps {
  initial: LiveTrade[];
  incoming: LiveTrade | null;
  maxRows?: number;
}

/**
 * A scrolling live tape of trades.
 *
 * Maintains its own rolling buffer. Receives initial seed rows on mount,
 * then prepends each incoming live trade with a brief highlight to show
 * it's new.
 */
export function LiveTrades({ initial, incoming, maxRows = 50 }: LiveTradesProps) {
  const [rows, setRows] = useState<LiveTrade[]>(initial);
  const [flashIds, setFlashIds] = useState<Set<string>>(new Set());

  // Reset rows when the parent supplies a new initial set
  // (e.g. user navigated to a different symbol)
  useEffect(() => {
    setRows(initial);
  }, [initial]);

  useEffect(() => {
    if (!incoming) return;
    setRows((prev) => {
      // Dedupe by venue_trade_id; ignore if we already have it
      if (prev.some((r) => r.venue_trade_id === incoming.venue_trade_id)) {
        return prev;
      }
      return [incoming, ...prev].slice(0, maxRows);
    });
    setFlashIds((prev) => new Set(prev).add(incoming.venue_trade_id));
    const id = incoming.venue_trade_id;
    const t = setTimeout(() => {
      setFlashIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, 1200);
    return () => clearTimeout(t);
  }, [incoming, maxRows]);

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-6 py-3">
        <h3 className="text-sm font-medium uppercase tracking-wide text-gray-500">
          Live tape ({rows.length})
        </h3>
      </div>
      {rows.length === 0 ? (
        <div className="px-6 py-8 text-center text-sm text-gray-500">
          Waiting for trades…
        </div>
      ) : (
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-6 py-2 font-medium">Time (UTC)</th>
                <th className="px-6 py-2 font-medium">Price</th>
                <th className="px-6 py-2 font-medium">Quantity</th>
                <th className="px-6 py-2 font-medium">Side</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((trade) => (
                <tr
                  key={trade.venue_trade_id}
                  className={cn(
                    "transition-colors",
                    flashIds.has(trade.venue_trade_id)
                      ? trade.side === "b"
                        ? "bg-green-50"
                        : trade.side === "s"
                          ? "bg-red-50"
                          : "bg-gray-50"
                      : "",
                  )}
                >
                  <td className="px-6 py-1.5 font-mono text-xs text-gray-600">
                    {new Date(trade.ts).toISOString().replace("T", " ").slice(11, 19)}
                  </td>
                  <td className="px-6 py-1.5 font-mono">{trade.price}</td>
                  <td className="px-6 py-1.5 font-mono">{trade.quantity}</td>
                  <td className="px-6 py-1.5">
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
        </div>
      )}
    </div>
  );
}
