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

export interface InstrumentCreate {
  asset_class: AssetClass;
  venue: string;
  base: string;
  quote: string;
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

// ----- Settings types -----

export interface ProfileResponse {
  user_id: string;
  auth0_sub: string;
  email: string | null;
  name: string | null;
  timezone: string;
  theme: "light" | "dark" | "system";
  notifications_enabled: boolean;
  created_at: string;
}

export interface ProfileUpdate {
  name?: string;
  timezone?: string;
  theme?: "light" | "dark" | "system";
  notifications_enabled?: boolean;
}

export interface ProfileSync {
  email?: string;
  name?: string;
}

export interface APICredentialSummary {
  id: string;
  service: string;
  label: string;
  last_four: string | null;
  created_at: string;
  last_used_at: string | null;
}

export interface APICredentialCreate {
  service: string;
  label: string;
  payload: Record<string, string>;
}

// Frontend mirror of backend SERVICE_FIELDS — add a service in both places.
export interface ServiceSchema {
  id: string; // matches backend key
  displayName: string;
  fields: { key: string; label: string; placeholder?: string }[];
  /** Which field's last-4 chars to display for identification later */
  primaryField: string;
  helpUrl?: string;
}

export const SERVICE_SCHEMAS: ServiceSchema[] = [
  {
    id: "binanceus",
    displayName: "Binance.US",
    fields: [
      { key: "api_key", label: "API Key", placeholder: "Your Binance.US API key" },
      { key: "secret_key", label: "Secret Key", placeholder: "Your Binance.US secret key" },
    ],
    primaryField: "api_key",
    helpUrl: "https://www.binance.us/usercenter/settings/api-management",
  },
  {
    id: "alpaca",
    displayName: "Alpaca",
    fields: [
      { key: "api_key_id", label: "API Key ID" },
      { key: "secret_key", label: "Secret Key" },
    ],
    primaryField: "api_key_id",
    helpUrl: "https://app.alpaca.markets/paper/dashboard/overview",
  },
];

// ----- Step 14 frontend mirror for available venues -----

export interface VenueSchema {
  id: string; // matches backend venue codes
  displayName: string;
  supportedAssetClasses: AssetClass[];
  status: "available" | "coming_soon";
  notes?: string;
  /** Quick-pick suggestions for the "add instrument" form */
  suggestedPairs?: { base: string; quote: string }[];
}

export const VENUE_SCHEMAS: VenueSchema[] = [
  {
    id: "BINANCEUS",
    displayName: "Binance.US",
    supportedAssetClasses: ["crypto_spot"],
    status: "available",
    notes:
      "Live ingestion via Binance.US WebSocket Streams. " +
      "Symbols verified against the public exchange info endpoint before save.",
    suggestedPairs: [
      { base: "BTC", quote: "USDT" },
      { base: "ETH", quote: "USDT" },
      { base: "SOL", quote: "USDT" },
      { base: "BTC", quote: "USD" },
      { base: "ETH", quote: "USD" },
    ],
  },
  {
    id: "ALPACA",
    displayName: "Alpaca (US equities + crypto)",
    supportedAssetClasses: ["equity", "crypto_spot"],
    status: "coming_soon",
    notes: "Adapter scheduled for Phase 4 (live execution layer).",
  },
];
