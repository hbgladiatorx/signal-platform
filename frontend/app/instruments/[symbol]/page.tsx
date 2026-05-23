"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { LiveTrades, type LiveTrade } from "@/components/charts/LiveTrades";
import { PriceChart } from "@/components/charts/PriceChart";
import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import type {
  Instrument,
  LatestQuoteResponse,
  QuoteChartPoint,
  TradeEvent,
  WSServerMessage,
} from "@/lib/types";
import { useWebSocket } from "@/lib/useWebSocket";

export default function InstrumentDetailPage() {
  const params = useParams<{ symbol: string }>();
  const symbol = decodeURIComponent(params.symbol);
  const api = useApi();

  // ----- Initial data (REST) -----
  const instrumentQuery = useQuery({
    queryKey: ["instrument", symbol],
    queryFn: () =>
      api.get<Instrument>(`/instruments/${encodeURIComponent(symbol)}`),
  });

  const latestQuoteQuery = useQuery({
    queryKey: ["quote", "latest", symbol],
    queryFn: () =>
      api.get<LatestQuoteResponse>(
        `/market/quote/latest?symbol=${encodeURIComponent(symbol)}`,
      ),
    // No polling — we get live updates via WS.
  });

  const chartHistoryQuery = useQuery({
    queryKey: ["chart", "history", symbol],
    queryFn: () =>
      api.get<QuoteChartPoint[]>(
        `/market/quotes/recent?symbol=${encodeURIComponent(symbol)}&minutes=60`,
      ),
  });

  const initialTradesQuery = useQuery({
    queryKey: ["trades", "initial", symbol],
    queryFn: () =>
      api.get<TradeEvent[]>(
        `/market/trades?symbol=${encodeURIComponent(symbol)}&limit=20`,
      ),
  });

  // ----- Live state from WS -----
  const [liveMid, setLiveMid] = useState<
    { ts: string; mid: number } | null
  >(null);
  const [liveQuote, setLiveQuote] = useState<{
    ts: string;
    bid: string | null;
    ask: string | null;
  } | null>(null);
  const [liveTrade, setLiveTrade] = useState<LiveTrade | null>(null);

  const handleMessage = useCallback(
    (msg: WSServerMessage) => {
      if (msg.type === "quote" && msg.symbol === symbol) {
        const bid = msg.data.bid ? Number.parseFloat(msg.data.bid) : null;
        const ask = msg.data.ask ? Number.parseFloat(msg.data.ask) : null;
        if (bid !== null && ask !== null && Number.isFinite(bid) && Number.isFinite(ask)) {
          setLiveMid({
            ts: msg.data.ts,
            mid: (bid + ask) / 2,
          });
        }
        setLiveQuote({
          ts: msg.data.ts,
          bid: msg.data.bid ?? null,
          ask: msg.data.ask ?? null,
        });
      } else if (msg.type === "trade" && msg.symbol === symbol) {
        setLiveTrade({
          ts: msg.data.ts,
          price: msg.data.price,
          quantity: msg.data.quantity,
          side:
            msg.data.side === "b" || msg.data.side === "s"
              ? msg.data.side
              : null,
          venue_trade_id: msg.data.venue_trade_id,
        });
      }
    },
    [symbol],
  );

  // Subscribe on connect; resubscribe on reconnect
  const sendMessageRef = useRef<((m: WSServerMessage) => void) | null>(null);
  const handleConnected = useCallback(() => {
    sendMessageRef.current?.({ type: "subscribe", symbol } as unknown as WSServerMessage);
  }, [symbol]);

  const { isConnected, isAuthenticated, sendMessage } = useWebSocket({
    onMessage: handleMessage,
    onConnected: handleConnected,
  });

  // Keep the sendMessage ref current
  useEffect(() => {
    sendMessageRef.current = sendMessage as unknown as (m: WSServerMessage) => void;
  }, [sendMessage]);

  // Send subscribe when authenticated AND when symbol changes
  useEffect(() => {
    if (isAuthenticated) {
      sendMessage({ type: "subscribe", symbol });
    }
  }, [isAuthenticated, symbol, sendMessage]);

  // ----- Derived display values -----
  const initialTrades: LiveTrade[] = useMemo(
    () =>
      (initialTradesQuery.data ?? []).map((t) => ({
        ts: t.ts,
        price: t.price,
        quantity: t.quantity,
        side: t.side,
        venue_trade_id: t.venue_trade_id,
      })),
    [initialTradesQuery.data],
  );

  const chartHistory = useMemo(
    () =>
      (chartHistoryQuery.data ?? []).map((p) => ({ ts: p.ts, mid: p.mid })),
    [chartHistoryQuery.data],
  );

  // Latest quote: live takes precedence over REST snapshot
  const displayQuote = liveQuote ?? {
    ts: latestQuoteQuery.data?.ts ?? "",
    bid: latestQuoteQuery.data?.bid ?? null,
    ask: latestQuoteQuery.data?.ask ?? null,
  };
  const mid =
    displayQuote.bid && displayQuote.ask
      ? (
          (Number.parseFloat(displayQuote.bid) +
            Number.parseFloat(displayQuote.ask)) /
          2
        ).toFixed(2)
      : "—";
  const spread =
    displayQuote.bid && displayQuote.ask
      ? (
          Number.parseFloat(displayQuote.ask) -
          Number.parseFloat(displayQuote.bid)
        ).toFixed(4)
      : "—";

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
          <div className="mt-3 grid grid-cols-2 gap-4 text-sm md:grid-cols-5">
            <Field label="Bid" value={displayQuote.bid ?? "—"} />
            <Field label="Ask" value={displayQuote.ask ?? "—"} />
            <Field label="Mid" value={mid} />
            <Field label="Spread" value={spread} />
            <Field
              label="Source"
              value={liveQuote ? "live" : latestQuoteQuery.data ? "snapshot" : "—"}
            />
          </div>
        </div>

        <PriceChart canonicalSymbol={symbol} />

        <LiveTrades initial={initialTrades} incoming={liveTrade} />
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
