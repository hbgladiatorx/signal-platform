// Trader-side API. Mock now → Supabase later.
import {
  strategies, signals, marketTiles, getEquityCurve, getUserEquityCurve,
  takenSignals, followedStrategyIds, marketNews,
} from "../mockData";
import { readFollowedOverlay, toggleFollow, getTraderSeeded } from "../user-prefs";
import type { Strategy, Signal } from "../types";

const wait = (ms = 120) => new Promise((r) => setTimeout(r, ms));

export async function getMarketNews() { await wait(60); return marketNews; }

export async function getStrategies(): Promise<Strategy[]> {
  await wait();
  return strategies;
}
export async function getStrategyById(id: string) {
  await wait();
  return strategies.find((s) => s.id === id);
}

/** Effective followed ids = defaults ∪ overlay.added − overlay.removed */
export function getEffectiveFollowedIds(): string[] {
  const overlay = readFollowedOverlay();
  const set = new Set<string>(followedStrategyIds);
  overlay.added.forEach((id) => set.add(id));
  overlay.removed.forEach((id) => set.delete(id));
  return [...set];
}

export async function getFollowedStrategies() {
  await wait();
  const ids = new Set(getEffectiveFollowedIds());
  return strategies.filter((s) => ids.has(s.id));
}
export async function getSignals(opts?: { strategyId?: string; limit?: number }): Promise<Signal[]> {
  await wait();
  let list = [...signals].sort((a, b) => +new Date(b.firedAt) - +new Date(a.firedAt));
  if (opts?.strategyId) list = list.filter((s) => s.strategyId === opts.strategyId);
  if (opts?.limit) list = list.slice(0, opts.limit);
  return list;
}
export async function getSignalById(id: string) {
  await wait();
  return signals.find((s) => s.id === id);
}
export async function getRecentSignals(limit = 10) { return getSignals({ limit }); }
export async function getMarketOverview() { await wait(60); return marketTiles; }
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
  const avgR = taken.reduce((s, t) => s + (t.pnlR ?? 0), 0) / Math.max(1, total);
  let peak = -Infinity, maxDD = 0;
  for (const p of equity) { peak = Math.max(peak, p.equity); const dd = (p.equity - peak) / peak; if (dd < maxDD) maxDD = dd; }
  return { equity, taken, kpis: { totalTaken: total, winRate, avgR, maxDrawdown: maxDD } };
}
export async function subscribeToStrategy(id: string) { await wait(); toggleFollow(id, true); return { ok: true }; }
export async function unsubscribeFromStrategy(id: string) { await wait(); toggleFollow(id, false); return { ok: true }; }
export async function markSignalTaken(_signalId: string, _fillPrice: number) { await wait(); return { ok: true }; }
export async function sendOrderToBroker(_signalId: string, _broker: string) { await wait(400); return { ok: true }; }
