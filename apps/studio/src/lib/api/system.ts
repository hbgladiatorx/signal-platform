// System / instruments API — operational + market-data browsing.
// Wired to the FastAPI /instruments and /system routers.
import { api } from "@/lib/api/client";

export type AssetClass = "crypto_spot" | "equity" | "option";

export interface Instrument {
  id: string;
  asset_class: AssetClass;
  canonical_symbol: string;
  venue: string;
  native_symbol: string;
  base: string | null;
  quote: string | null;
  metadata: Record<string, unknown> | null;
  active: boolean;
}

export interface InstrumentCoverage {
  canonical_symbol: string;
  bars: number;
  first: string | null;
  last: string | null;
}

export const listInstruments = (params?: {
  venue?: string;
  asset_class?: AssetClass;
  active?: boolean;
}) => api.get<Instrument[]>("/instruments", params);

export const getInstrumentCoverage = (asset_class?: AssetClass) =>
  api.get<InstrumentCoverage[]>("/instruments/coverage", asset_class ? { asset_class } : undefined);

// ---- System health -------------------------------------------------------

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

export interface StreamStatus {
  stream: string;
  length: number;
  groups: Array<Record<string, unknown>>;
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

export const getSystemHealth = () =>
  api.get<SystemHealthDetail>("/system/health/detail");

// ---- Connections / config status ----------------------------------------

export interface ConnectionsStatus {
  ai_copilot: boolean;
  crypto_data: boolean;
  stock_data_alpaca: boolean;
  stock_data_polygon: boolean;
  trading_alpaca_paper: boolean;
  trading_binanceus: boolean;
  key_encryption: boolean;
}

/** Which platform integrations are configured on the server (booleans only). */
export const getConnections = () => api.get<ConnectionsStatus>("/system/connections");

// ---- Live resource metrics (floating health widget) ----------------------

export interface SystemMetrics {
  ts: number;
  cpu_percent: number;
  cpu_cores: number;
  load_avg: number[] | null;
  mem_used: number;
  mem_total: number;
  mem_percent: number;
  disk_used: number;
  disk_total: number;
  disk_percent: number;
  net_bytes_sent: number;
  net_bytes_recv: number;
}

export const getSystemMetrics = () => api.get<SystemMetrics>("/system/metrics");
