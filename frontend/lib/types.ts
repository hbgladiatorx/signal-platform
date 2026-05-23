/**
 * TypeScript types mirroring the backend Pydantic models.
 */

export type AssetClass = "crypto_spot" | "crypto_perp" | "option" | "equity";
export type TradeSide = "b" | "s";
export type BarResolution = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";

export interface Instrument {
  id: number;
  asset_class: AssetClass;
  canonical_symbol: string;
  venue: string;
  native_symbol: string;
  base: string | null;
  quote: string | null;
  metadata: Record<string, unknown>;
  active: boolean;
}

export interface TradeEvent {
  canonical_symbol: string;
  ts: string;
  price: string;
  quantity: string;
  side: TradeSide | null;
  venue_trade_id: string;
}

export interface QuoteL1Event {
  canonical_symbol: string;
  ts: string;
  bid: string | null;
  bid_size: string | null;
  ask: string | null;
  ask_size: string | null;
}

export interface LatestQuoteResponse extends QuoteL1Event {
  mid: string | null;
  spread: string | null;
  spread_bps: string | null;
}

export interface QuoteChartPoint {
  ts: string;
  bid: string | null;
  ask: string | null;
  mid: string | null;
}

export interface HealthResponse {
  status: "alive" | "ready" | "degraded";
  ts: string;
}

export interface MeResponse {
  sub: string | null;
  iss: string | null;
  aud: string | null;
  scope: string | null;
  exp: number | null;
  iat: number | null;
  claims: Record<string, unknown>;
}

// ----- WebSocket message types -----

export type WSClientMessage =
  | { type: "auth"; token: string }
  | { type: "subscribe"; symbol: string }
  | { type: "unsubscribe"; symbol: string }
  | { type: "ping" };

export type WSServerMessage =
  | { type: "auth.ok"; sub: string | null }
  | { type: "subscribed"; symbol: string }
  | { type: "unsubscribed"; symbol: string }
  | { type: "pong" }
  | { type: "error"; message: string }
  | {
      type: "trade";
      symbol: string;
      data: {
        canonical_symbol: string;
        ts: string;
        price: string;
        quantity: string;
        side?: string;
        venue_trade_id: string;
      };
    }
  | {
      type: "quote";
      symbol: string;
      data: {
        canonical_symbol: string;
        ts: string;
        bid?: string;
        bid_size?: string;
        ask?: string;
        ask_size?: string;
      };
    };

// ----- System Health detail types -----

export interface IngestionInstrumentStatus {
  canonical_symbol: string;
  venue: string;
  last_trade_ts: string | null;
  last_quote_ts: string | null;
  last_trade_age_s: number | null;
  last_quote_age_s: number | null;
  trades_last_5m: number;
  quotes_last_5m: number;
}

export interface StreamGroupSummary {
  name: string;
  consumers: number;
  pending: number;
  lag: number | null;
  last_delivered_id: string | null;
}

export interface StreamStatus {
  stream: string;
  length: number;
  groups: StreamGroupSummary[];
}

export interface TableStats {
  name: string;
  approximate_rows: number;
  earliest_ts: string | null;
  latest_ts: string | null;
}

export interface SystemHealthDetail {
  ts: string;
  duration_ms: number;
  instruments_total: number;
  instruments_active: number;
  ingestion: IngestionInstrumentStatus[];
  streams: StreamStatus[];
  tables: TableStats[];
  persistence_pending_total: number;
  ws_broadcast_pending_total: number;
}
