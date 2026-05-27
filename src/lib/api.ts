// All Supabase calls live here. Swap mock returns for supabase.from('...').select() later.
//
// Expected tables:
//  - strategies (id, name, description, asset_class, dev_id, status, stats jsonb, created_at)
//  - signals (id, strategy_id, symbol, direction, entry, stop, target, status, fired_at, closed_at, outcome)
//  - subscriptions (user_id, strategy_id, created_at)
//  - taken_signals (user_id, signal_id, fill_price, outcome, pnl)
//  - users (extends auth.users)
//  - broker_connections (user_id, broker, status, encrypted_credentials)
//
// Every data-fetch in the app goes through this file. No component imports mockData directly.

import {
  strategies, signals, marketTiles, getEquityCurve, getUserEquityCurve,
  takenSignals, followedStrategyIds,
} from "./mockData";
import type { Strategy, Signal } from "./types";

const wait = (ms = 120) => new Promise((r) => setTimeout(r, ms));

export async function getStrategies(): Promise<Strategy[]> {
  await wait();
  // TODO: return supabase.from('strategies').select('*');
  return strategies;
}

export async function getStrategyById(id: string): Promise<Strategy | undefined> {
  await wait();
  return strategies.find((s) => s.id === id);
}

export async function getFollowedStrategies(): Promise<Strategy[]> {
  await wait();
  return strategies.filter((s) => followedStrategyIds.includes(s.id));
}

export async function getSignals(opts?: { strategyId?: string; limit?: number }): Promise<Signal[]> {
  await wait();
  let list = [...signals].sort((a, b) => +new Date(b.firedAt) - +new Date(a.firedAt));
  if (opts?.strategyId) list = list.filter((s) => s.strategyId === opts.strategyId);
  if (opts?.limit) list = list.slice(0, opts.limit);
  return list;
}

export async function getSignalById(id: string): Promise<Signal | undefined> {
  await wait();
  return signals.find((s) => s.id === id);
}

export async function getRecentSignals(limit = 10): Promise<Signal[]> {
  return getSignals({ limit });
}

export async function getMarketOverview() {
  await wait(60);
  return marketTiles;
}

export async function getStrategyEquity(strategyId: string, days = 30) {
  await wait();
  return getEquityCurve(strategyId, days);
}

export async function getUserPerformance(days = 30) {
  await wait();
  const equity = getUserEquityCurve(days);
  const taken = takenSignals;
  const wins = taken.filter((t) => t.outcome === "HIT_TARGET").length;
  const total = taken.length;
  const winRate = total ? wins / total : 0;
  const avgR =
    taken.reduce((sum, t) => sum + (t.pnlR ?? 0), 0) / Math.max(1, total);
  // simple peak-to-trough on equity
  let peak = -Infinity;
  let maxDD = 0;
  for (const p of equity) {
    peak = Math.max(peak, p.equity);
    const dd = (p.equity - peak) / peak;
    if (dd < maxDD) maxDD = dd;
  }
  return {
    equity,
    taken,
    kpis: { totalTaken: total, winRate, avgR, maxDrawdown: maxDD },
  };
}

export async function subscribeToStrategy(_id: string) {
  await wait();
  // TODO: supabase.from('subscriptions').insert({ strategy_id: _id, user_id: ... })
  return { ok: true };
}

export async function unsubscribeFromStrategy(_id: string) {
  await wait();
  return { ok: true };
}

export async function markSignalTaken(_signalId: string, _fillPrice: number) {
  await wait();
  // TODO: supabase.from('taken_signals').insert(...)
  return { ok: true };
}

export async function sendOrderToBroker(_signalId: string, _broker: string) {
  await wait(400);
  // TODO: call broker bridge edge function
  return { ok: true };
}
