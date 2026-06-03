// frontend/lib/paper-types.ts
// Types + formatters for live paper trading.
// Mirrors the Pydantic models in services/api/routers/paper_sessions.py.

export type PaperStatus =
  | "starting"
  | "running"
  | "stopping"
  | "stopped"
  | "error";

export type PaperAssetClass = "crypto_spot" | "equity" | "option";

// 'paper' = simulated (Alpaca paper); 'live' = REAL money (Binance.US spot).
export type SessionMode = "paper" | "live";

export interface PaperSessionSummary {
  id: string;
  strategy_name: string;
  symbols: string[];
  asset_class: PaperAssetClass;
  bar_resolution: string;
  mode: SessionMode;
  status: PaperStatus;
  created_at: string;
  started_at: string | null;
  stopped_at: string | null;
  current_equity: number | string | null;
  realized_pnl: number | string | null;
  num_orders: number;
  num_fills: number;
}

export interface PaperSessionDetail extends PaperSessionSummary {
  params_json: Record<string, unknown>;
  starting_cash: number | string;
  max_order_notional: number | string | null;
  max_daily_loss: number | string | null;
  cancel_open_on_stop: boolean;
  error_message: string | null;
  last_processed_bar_ts: string | null;
  last_bar_count: number;
}

export interface PaperOrder {
  id: string;
  client_order_id: string;
  broker_order_id: string | null;
  symbol: string;
  side: string;
  order_type: string;
  quantity: number | string;
  limit_price: number | string | null;
  time_in_force: string;
  status: string;
  filled_quantity: number | string;
  avg_fill_price: number | string | null;
  error_message: string | null;
  submitted_ts: string;
  created_at: string;
}

export interface PaperFill {
  id: number;
  order_id: string;
  symbol: string;
  side: string;
  quantity: number | string;
  price: number | string;
  fee: number | string;
  filled_ts: string;
}

export interface PaperPosition {
  symbol: string;
  quantity: number | string;
  avg_cost: number | string;
  realized_pnl: number | string;
  updated_at: string;
}

export interface PaperEquityPoint {
  ts: string;
  cash: number | string;
  positions_value: number | string;
  total_equity: number | string;
}

export interface CreatePaperSessionRequest {
  strategy_name: string;
  params: Record<string, unknown>;
  symbols: string[];
  asset_class: PaperAssetClass;
  bar_resolution: string;
  api_credential_id: string;
  starting_cash: number;
  max_order_notional?: number | null;
  max_daily_loss?: number | null;
  cancel_open_on_stop: boolean;
}

// GET/POST/DELETE /live/killswitch
export interface KillSwitchState {
  engaged: boolean;
}

// A row from GET /settings/api-keys (APICredentialSummary).
export interface ApiCredential {
  id: string;
  service: string;
  label: string;
  last_four: string | null;
  created_at: string;
}

// ============================================================
// Constants
// ============================================================
export const BAR_RESOLUTIONS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;

export const ASSET_CLASSES: {
  value: PaperAssetClass;
  label: string;
  hint: string;
}[] = [
  {
    value: "crypto_spot",
    label: "Crypto",
    hint: "Signal from existing Binance.US bars; orders to Alpaca crypto paper.",
  },
  {
    value: "equity",
    label: "US Equities",
    hint: "Requires Alpaca market-data ingestion (Stage 2) for the symbol.",
  },
];

// ============================================================
// Formatters
// ============================================================
export function num(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

export function fmtMoney(v: number | string | null | undefined): string {
  const n = num(v);
  if (n === null) return "—";
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

export function fmtQty(v: number | string | null | undefined): string {
  const n = num(v);
  if (n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 8 });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function statusColor(status: PaperStatus): string {
  switch (status) {
    case "running":
      return "bg-emerald-100 text-emerald-800 border-emerald-200";
    case "starting":
      return "bg-blue-100 text-blue-800 border-blue-200";
    case "stopping":
      return "bg-amber-100 text-amber-800 border-amber-200";
    case "stopped":
      return "bg-gray-100 text-gray-700 border-gray-200";
    case "error":
      return "bg-red-100 text-red-800 border-red-200";
  }
}

export function orderStatusColor(status: string): string {
  switch (status) {
    case "filled":
      return "bg-emerald-100 text-emerald-800 border-emerald-200";
    case "partially_filled":
    case "accepted":
      return "bg-blue-100 text-blue-800 border-blue-200";
    case "pending":
      return "bg-gray-100 text-gray-700 border-gray-200";
    case "canceled":
    case "expired":
      return "bg-amber-100 text-amber-800 border-amber-200";
    case "rejected":
    case "error":
      return "bg-red-100 text-red-800 border-red-200";
    default:
      return "bg-gray-100 text-gray-700 border-gray-200";
  }
}

export function isActive(status: PaperStatus): boolean {
  return status === "starting" || status === "running" || status === "stopping";
}

// Visual treatment for the session mode badge. Live = loud red (real money).
export function modeBadge(mode: SessionMode): { label: string; cls: string } {
  return mode === "live"
    ? { label: "LIVE", cls: "bg-red-600 text-white border-red-700" }
    : { label: "paper", cls: "bg-gray-100 text-gray-600 border-gray-200" };
}
