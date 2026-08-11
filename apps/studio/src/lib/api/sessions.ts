// Paper / live trading sessions + kill switch.
// Wired to the FastAPI /paper-sessions and /live routers. A session runs a
// strategy against live market data, routing orders through a stored broker
// credential (Alpaca paper, or Binance.US live).
import { api } from "@/lib/api/client";

export interface PaperSessionSummary {
  id: string;
  strategy_name: string;
  symbols: string[];
  asset_class: string;
  bar_resolution: string;
  mode: string; // "paper" | "live"
  status: string;
  created_at: string;
  started_at: string | null;
  stopped_at: string | null;
  current_equity: number | string | null;
  realized_pnl: number | string | null;
  num_orders: number;
  num_fills: number;
  // Last time the worker proved it's executing this session (ISO). A running
  // session with a stale/absent heartbeat means no live worker — see sessionLive().
  last_heartbeat_at?: string | null;
  // Present on the session DETAIL response (GET /paper-sessions/{id}); the
  // baseline a paper session starts with, used to seed the equity display.
  starting_cash?: number | string | null;
}

export interface CreatePaperSessionInput {
  strategy_name: string;
  params?: Record<string, unknown>;
  symbols: string[];
  asset_class?: string;
  bar_resolution?: string;
  api_credential_id: string;
  starting_cash?: number;
  max_order_notional?: number;
  cancel_open_on_stop?: boolean;
  max_daily_loss?: number;
}

export interface OrderRow {
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
}

export interface PositionRow {
  symbol: string;
  quantity: number | string;
  avg_cost: number | string;
  realized_pnl: number | string;
  updated_at: string;
}

export interface SessionEquityRow {
  ts: string;
  cash: number | string;
  positions_value: number | string;
  total_equity: number | string;
}

// A 'running' session is only truly live if a worker recently stamped its
// heartbeat. Server cadence is 20s; allow a few missed beats before flagging so
// a brief hiccup or clock skew doesn't cause false alarms. Returns true when the
// session claims to be running but no worker appears to be executing it.
export function sessionNoWorker(s: {
  status: string;
  last_heartbeat_at?: string | null;
  started_at?: string | null;
}): boolean {
  if (s.status !== "running") return false;
  const STALE_MS = 90_000;
  const hbAge = s.last_heartbeat_at
    ? Date.now() - new Date(s.last_heartbeat_at).getTime()
    : Infinity;
  const startedAge = s.started_at
    ? Date.now() - new Date(s.started_at).getTime()
    : 0;
  // Don't flag a just-started session that simply hasn't beat yet.
  return hbAge > STALE_MS && startedAge > STALE_MS;
}

export const listSessions = () =>
  api.get<PaperSessionSummary[]>("/paper-sessions");

export const getSession = (id: string) =>
  api.get<PaperSessionSummary>(`/paper-sessions/${id}`);

export const createSession = (body: CreatePaperSessionInput) =>
  api.post<{ id: string; status: string }>("/paper-sessions", body);

export const getSessionOrders = (id: string) =>
  api.get<OrderRow[]>(`/paper-sessions/${id}/orders`);

export const getSessionPositions = (id: string) =>
  api.get<PositionRow[]>(`/paper-sessions/${id}/positions`);

export const getSessionEquity = (id: string) =>
  api.get<SessionEquityRow[]>(`/paper-sessions/${id}/equity`);

export const stopSession = (id: string) =>
  api.post<void>(`/paper-sessions/${id}/stop`);

export const flattenSession = (id: string) =>
  api.post<void>(`/paper-sessions/${id}/flatten`);

// ---------- kill switch ----------
// Platform-wide pause on live (real-money) order submission. Paper sessions
// are unaffected. Engaging/disengaging take no body.
export interface KillSwitchState {
  engaged: boolean;
}

export const getKillSwitch = () =>
  api.get<KillSwitchState>("/live/killswitch");

export const engageKillSwitch = () =>
  api.post<KillSwitchState>("/live/killswitch");

export const disengageKillSwitch = () =>
  api.del<KillSwitchState>("/live/killswitch");
