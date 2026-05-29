// src/lib/api/trader.ts
import { supabase } from '@/integrations/supabase/client';

export async function getCatalog(assetClass?: string) {
  let q = supabase
    .from('signal_products')
    .select('*')
    .eq('is_published', true)
    .order('forward_win_rate', { ascending: false });

  if (assetClass && assetClass !== 'all') {
    q = q.eq('asset_class', assetClass);
  }

  const { data, error } = await q;
  if (error) throw error;
  return data ?? [];
}

export async function getProduct(productId: string) {
  const { data, error } = await supabase
    .from('signal_products')
    .select('*')
    .eq('id', productId)
    .single();
  if (error) throw error;
  return data;
}

export async function getMySubscriptions() {
  const { data, error } = await supabase
    .from('product_subscriptions')
    .select('*, signal_products(*)')
    .is('ended_at', null);
  if (error) throw error;
  return data ?? [];
}

export async function isSubscribed(productId: string) {
  const { data, error } = await supabase
    .from('product_subscriptions')
    .select('id')
    .eq('product_id', productId)
    .is('ended_at', null)
    .maybeSingle();
  if (error) throw error;
  return !!data;
}

export async function subscribeToProduct(productId: string) {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) throw new Error('Not authenticated');

  const { data, error } = await supabase
    .from('product_subscriptions')
    .insert({
      user_id: user.id,
      product_id: productId,
      paid: false,
    })
    .select()
    .single();
  if (error) throw error;
  return data;
}

export async function unsubscribeFromProduct(productId: string) {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) throw new Error('Not authenticated');

  const { error } = await supabase
    .from('product_subscriptions')
    .update({ ended_at: new Date().toISOString() })
    .eq('user_id', user.id)
    .eq('product_id', productId)
    .is('ended_at', null);
  if (error) throw error;
}

export async function getRecentSignals(limit = 50) {
  const { data, error } = await supabase
    .from('signals')
    .select('*, signal_products(name, asset_class, slug)')
    .order('fired_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return data ?? [];
}

export async function getSignal(signalId: string) {
  const { data, error } = await supabase
    .from('signals')
    .select('*, signal_products(name, asset_class, slug, description)')
    .eq('id', signalId)
    .single();
  if (error) throw error;
  return data;
}

export async function getOpenSignals() {
  const { data, error } = await supabase
    .from('signals')
    .select('*, signal_products(name, asset_class)')
    .eq('status', 'open')
    .order('fired_at', { ascending: false });
  if (error) throw error;
  return data ?? [];
}

export async function getTakenSignals() {
  const { data, error } = await supabase
    .from('taken_signals')
    .select('*, signals(*, signal_products(name, asset_class))')
    .order('taken_at', { ascending: false });
  if (error) throw error;
  return data ?? [];
}

export async function markSignalTaken(
  signalId: string,
  fillPrice: number,
  source: 'manual' | 'broker' | 'agent'
) {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) throw new Error('Not authenticated');

  const { data, error } = await supabase
    .from('taken_signals')
    .insert({
      user_id: user.id,
      signal_id: signalId,
      fill_price: fillPrice,
      source,
    })
    .select()
    .single();
  if (error) throw error;
  return data;
}

export async function getUserPreferences() {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return {};

  const { data, error } = await supabase
    .from('user_preferences')
    .select('prefs')
    .eq('user_id', user.id)
    .maybeSingle();
  if (error) throw error;
  return data?.prefs ?? {};
}

export async function updateUserPreferences(prefs: any) {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) throw new Error('Not authenticated');

  const { error } = await supabase
    .from('user_preferences')
    .upsert({
      user_id: user.id,
      prefs,
      updated_at: new Date().toISOString(),
    });
  if (error) throw error;
}

export async function getPlanState() {
  const { data, error } = await supabase
    .from('plan_state')
    .select('*')
    .maybeSingle();
  if (error) throw error;
  return data;
}

export function subscribeToSignals(onNewSignal: (signal: any) => void) {
  const channel = supabase
    .channel('signals-realtime')
    .on('postgres_changes',
      { event: 'INSERT', schema: 'public', table: 'signals' },
      (payload) => onNewSignal(payload.new))
    .subscribe();
  return () => supabase.removeChannel(channel);
}

export function subscribeToSignalUpdates(onUpdate: (signal: any) => void) {
  const channel = supabase
    .channel('signals-updates')
    .on('postgres_changes',
      { event: 'UPDATE', schema: 'public', table: 'signals' },
      (payload) => onUpdate(payload.new))
    .subscribe();
  return () => supabase.removeChannel(channel);
}

// ─────────────────────────────────────────────────────────────
// Legacy compatibility shims — bridge old UI to new schema.
// Follow/unfollow now hits product_subscriptions (no localStorage).
// ─────────────────────────────────────────────────────────────
import { useQuery } from "@tanstack/react-query";
import type { Strategy, Signal, EquityPoint, TakenSignal, AssetClass } from "../types";

function mapProductRow(row: any): Strategy {
  const ac = (row.asset_class ?? "stocks") as AssetClass;
  return {
    id: row.id,
    name: row.name ?? row.slug ?? "Untitled",
    description: row.description ?? "",
    longDescription: row.description ?? "",
    entryRules: "",
    exitRules: "",
    assetClass: ac,
    devHandle: "@bayn",
    status: "Watching",
    stage: "Published",
    edgeVerified: row.gate_status === "passed" || row.gate_status === "live" || row.gate_status === 3,
    symbols: [],
    lastSignalAt: row.updated_at ?? row.created_at ?? new Date().toISOString(),
    createdAt: row.created_at ?? new Date().toISOString(),
    stats: {
      sharpe: 0,
      winRate: typeof row.forward_win_rate === "number" ? row.forward_win_rate : 0,
      maxDrawdown: 0,
      sampleSize: 0,
      avgR: 0,
      liveDays: 0,
      subscribers: 0,
    },
  };
}

export async function getStrategies(): Promise<Strategy[]> {
  const rows = await getCatalog();
  return rows.map(mapProductRow);
}
export async function getStrategyById(id: string): Promise<Strategy | undefined> {
  try { const row = await getProduct(id); return row ? mapProductRow(row) : undefined; }
  catch { return undefined; }
}

// ---- Followed (real DB) ----
let _followedCache: string[] = [];

export async function getFollowedProductIds(): Promise<string[]> {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) { _followedCache = []; return []; }
  const { data, error } = await supabase
    .from("product_subscriptions")
    .select("product_id")
    .eq("user_id", user.id)
    .is("ended_at", null);
  if (error) throw error;
  const ids = (data ?? []).map((r: any) => r.product_id as string);
  _followedCache = ids;
  return ids;
}

/** React hook — drives the cache for sync callers. */
export function useFollowedIds() {
  const q = useQuery({ queryKey: ["followed"], queryFn: getFollowedProductIds });
  if (q.data) _followedCache = q.data;
  return q.data ?? [];
}

/** Legacy sync accessor — reads cache last hydrated by useFollowedIds(). */
export function getEffectiveFollowedIds(): string[] {
  return _followedCache;
}

export async function getFollowedStrategies(): Promise<Strategy[]> {
  const ids = new Set(await getFollowedProductIds());
  const all = await getStrategies();
  return all.filter((s) => ids.has(s.id));
}

export async function subscribeToStrategy(id: string) {
  const row = await subscribeToProduct(id);
  _followedCache = [..._followedCache.filter((x) => x !== id), id];
  return row;
}
export async function unsubscribeFromStrategy(id: string) {
  await unsubscribeFromProduct(id);
  _followedCache = _followedCache.filter((x) => x !== id);
  return { ok: true };
}

// ─────────────────────────────────────────────────────────────
// Signals + performance (real DB).
// ─────────────────────────────────────────────────────────────

function mapSignalStatus(row: any): SignalStatus {
  if (row.status === 'open' || row.status === 'OPEN') return 'OPEN';
  const o = (row.outcome ?? '').toString().toLowerCase();
  if (o === 'win' || o === 'target' || o === 'hit_target') return 'HIT_TARGET';
  if (o === 'loss' || o === 'stop' || o === 'hit_stop') return 'HIT_STOP';
  if (o === 'expired') return 'EXPIRED';
  if (row.status === 'closed') return 'EXPIRED';
  return 'OPEN';
}

function mapSignalRow(row: any): Signal {
  const prod = row.signal_products ?? {};
  const dir: Direction = (row.direction ?? '').toString().toLowerCase() === 'short' ? 'SHORT' : 'LONG';
  const entry = Number(row.entry_price ?? 0);
  const stop = Number(row.stop_price ?? 0);
  const target = Number(row.target_price ?? 0);
  const ac = (prod.asset_class ?? 'stocks') as AssetClass;
  const risk = Math.abs(entry - stop);
  let pnlR: number | undefined;
  if (row.pnl_pct != null && entry > 0 && risk > 0) {
    const moved = entry * (Number(row.pnl_pct) / 100);
    pnlR = (dir === 'LONG' ? moved : -moved) / risk;
  }
  return {
    id: row.id,
    strategyId: row.product_id,
    strategyName: prod.name ?? 'Strategy',
    assetClass: ac,
    symbol: row.symbol ?? '',
    direction: dir,
    entry,
    stop,
    target,
    status: mapSignalStatus(row),
    firedAt: row.fired_at ?? new Date().toISOString(),
    closedAt: row.closed_at ?? undefined,
    pnlR,
    reasoning: row.reasoning ?? '',
    priceSeries: [],
  };
}

import type { Direction } from '../types';

export async function getSignals(opts?: { strategyId?: string; limit?: number }): Promise<Signal[]> {
  let q = supabase
    .from('signals')
    .select('*, signal_products(name, asset_class, slug)')
    .order('fired_at', { ascending: false })
    .limit(opts?.limit ?? 200);
  if (opts?.strategyId) q = q.eq('product_id', opts.strategyId);
  const { data, error } = await q;
  if (error) throw error;
  return (data ?? []).map(mapSignalRow);
}

export async function getSignalById(id: string): Promise<Signal | undefined> {
  const { data, error } = await supabase
    .from('signals')
    .select('*, signal_products(name, asset_class, slug, description)')
    .eq('id', id)
    .maybeSingle();
  if (error) throw error;
  return data ? mapSignalRow(data) : undefined;
}

export async function getStrategyEquity(strategyId: string, days = 90): Promise<EquityPoint[]> {
  const since = new Date(Date.now() - days * 86_400_000).toISOString();
  const { data, error } = await supabase
    .from('signals')
    .select('closed_at, pnl_pct')
    .eq('product_id', strategyId)
    .not('closed_at', 'is', null)
    .gte('closed_at', since)
    .order('closed_at', { ascending: true });
  if (error) throw error;
  let eq = 1;
  return (data ?? []).map((r: any) => {
    eq = eq * (1 + Number(r.pnl_pct ?? 0) / 100);
    return { t: r.closed_at, equity: eq };
  });
}

export async function getUserPerformance(days = 90) {
  const since = new Date(Date.now() - days * 86_400_000).toISOString();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return { equity: [] as EquityPoint[], taken: [] as TakenSignal[], kpis: { totalTaken: 0, winRate: 0, avgR: 0, maxDrawdown: 0 } };
  }
  const { data, error } = await supabase
    .from('taken_signals')
    .select('*, signals(*, signal_products(name, asset_class, slug))')
    .eq('user_id', user.id)
    .gte('taken_at', since)
    .order('taken_at', { ascending: true });
  if (error) throw error;
  const rows = data ?? [];
  const taken: TakenSignal[] = rows.map((r: any) => {
    const sig = r.signals ? mapSignalRow(r.signals) : ({} as Signal);
    const pnlR = r.r_multiple != null ? Number(r.r_multiple) : undefined;
    const outcome: SignalStatus =
      r.outcome === 'win' ? 'HIT_TARGET' :
      r.outcome === 'loss' ? 'HIT_STOP' :
      r.outcome === 'expired' ? 'EXPIRED' : sig.status ?? 'OPEN';
    return {
      id: r.id,
      signalId: r.signal_id,
      signal: sig,
      takenAt: r.taken_at,
      fillPrice: Number(r.fill_price ?? 0),
      pnlR,
      outcome,
    };
  });
  // Equity curve from R-multiples (1R per trade baseline).
  let eq = 0;
  const equity: EquityPoint[] = taken
    .filter((t) => t.pnlR != null)
    .map((t) => { eq += t.pnlR!; return { t: t.takenAt, equity: eq }; });
  const closed = taken.filter((t) => t.outcome !== 'OPEN');
  const wins = closed.filter((t) => t.outcome === 'HIT_TARGET').length;
  const rs = taken.filter((t) => t.pnlR != null).map((t) => t.pnlR!);
  const avgR = rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : 0;
  let peak = 0, maxDD = 0;
  for (const p of equity) { peak = Math.max(peak, p.equity); maxDD = Math.min(maxDD, p.equity - peak); }
  return {
    equity,
    taken: taken.slice().reverse(),
    kpis: {
      totalTaken: taken.length,
      winRate: closed.length ? wins / closed.length : 0,
      avgR,
      maxDrawdown: Math.abs(maxDD) / 100,
    },
  };
}

export async function sendOrderToBroker(_signalId: string, _broker: string) { return { ok: true }; }
export async function getMarketOverview(): Promise<never[]> { return []; }
export async function getMarketNews(): Promise<never[]> { return []; }

