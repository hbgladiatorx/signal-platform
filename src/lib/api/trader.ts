// Trader-side API. Live data via Finnhub server functions; user-data
// (followed strategies, performance) returns empty until a real backend
// wires them up — we never seed mock content.
import { readFollowedOverlay, toggleFollow } from "../user-prefs";
import type { Strategy, Signal, MarketTile, EquityPoint, TakenSignal } from "../types";

const wait = (ms = 80) => new Promise((r) => setTimeout(r, ms));

/** Effective followed ids = overlay.added − overlay.removed.
 *  Brand-new accounts start with zero follows; no mock seeding. */
export function getEffectiveFollowedIds(): string[] {
  const overlay = readFollowedOverlay();
  const set = new Set<string>();
  overlay.added.forEach((id) => set.add(id));
  overlay.removed.forEach((id) => set.delete(id));
  return [...set];
}

// Strategy catalog is backend-driven. Until a real catalog backend exists,
// these return empty so the UI shows real empty states (no mock data).
export async function getStrategies(): Promise<Strategy[]> { await wait(); return []; }
export async function getStrategyById(_id: string): Promise<Strategy | undefined> { await wait(); return undefined; }
export async function getFollowedStrategies(): Promise<Strategy[]> { await wait(); return []; }

export async function getSignals(_opts?: { strategyId?: string; limit?: number }): Promise<Signal[]> {
  await wait();
  return [];
}
export async function getSignalById(_id: string): Promise<Signal | undefined> { await wait(); return undefined; }
export async function getRecentSignals(_limit = 10): Promise<Signal[]> { return []; }

/** Legacy shim — Home / sidebar still expect this shape but they should
 *  source live quotes via Finnhub. Always empty here. */
export async function getMarketOverview(): Promise<MarketTile[]> { await wait(); return []; }
/** Legacy shim — NewsTicker now calls Finnhub directly. */
export async function getMarketNews(): Promise<never[]> { await wait(); return []; }

export async function getStrategyEquity(_strategyId: string, _days = 30): Promise<EquityPoint[]> {
  await wait();
  return [];
}

export async function getUserPerformance(_days = 30) {
  await wait();
  return {
    equity: [] as EquityPoint[],
    taken: [] as TakenSignal[],
    kpis: { totalTaken: 0, winRate: 0, avgR: 0, maxDrawdown: 0 },
  };
}

export async function subscribeToStrategy(id: string) { await wait(); toggleFollow(id, true); return { ok: true }; }
export async function unsubscribeFromStrategy(id: string) { await wait(); toggleFollow(id, false); return { ok: true }; }
export async function markSignalTaken(_signalId: string, _fillPrice: number) { await wait(); return { ok: true }; }
export async function sendOrderToBroker(_signalId: string, _broker: string) { await wait(); return { ok: true }; }
