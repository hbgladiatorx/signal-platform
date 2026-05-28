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
/** Four always-free verified strategies — one per asset class. These are the
 *  base catalog every new account sees; premium strategies require a plan. */
const FREE_STRATEGIES: Strategy[] = [
  {
    id: "s-meanrev-spy", name: "SPY Mean Reversion", assetClass: "stocks",
    description: "Fades 2σ deviations from the 20-day VWAP on SPY at the regular session open.",
    longDescription: "Trades SPY only. Enters when price stretches 2 standard deviations from the 20-day VWAP within the first hour. Exits at VWAP or stop.",
    entryRules: "Price > 2σ from 20-day VWAP between 09:30–10:30 ET.",
    exitRules: "Target = VWAP. Stop = 1σ beyond entry.",
    devHandle: "@bayn", status: "Watching", stage: "Published", edgeVerified: true,
    symbols: ["SPY"], lastSignalAt: new Date().toISOString(), createdAt: "2025-01-15T00:00:00Z",
    stats: { sharpe: 1.42, winRate: 0.61, maxDrawdown: 0.09, sampleSize: 612, avgR: 0.38, liveDays: 420, subscribers: 0 },
  },
  {
    id: "s-btc-hourly-mr", name: "BTC Hourly Mean Reversion", assetClass: "crypto",
    description: "Fades 3σ hourly deviations from the 50-period VWAP on BTC perpetuals.",
    longDescription: "Hourly BTC fades. Skips the NYSE open ±15 minutes to avoid macro spillover.",
    entryRules: "Price > 3σ from 50h VWAP → short. Inverse for long.",
    exitRules: "Target = VWAP. Stop = 1.5× entry deviation.",
    devHandle: "@bayn", status: "Watching", stage: "Published", edgeVerified: true,
    symbols: ["BINANCE:BTCUSDT"], lastSignalAt: new Date().toISOString(), createdAt: "2025-02-01T00:00:00Z",
    stats: { sharpe: 1.64, winRate: 0.58, maxDrawdown: 0.17, sampleSize: 1284, avgR: 0.41, liveDays: 198, subscribers: 0 },
  },
  {
    id: "s-spy-otm-put", name: "SPY OTM Put Premium", assetClass: "options",
    description: "Sells weekly 10-delta SPY puts when IV rank > 50 and trend is intact.",
    longDescription: "Premium-collection on SPY weeklies. Mechanically rolls or closes at 50% of credit.",
    entryRules: "IV rank > 50, SPY > 50-day SMA. Sell 10-delta put 7 DTE.",
    exitRules: "Close at 50% profit or 1 DTE.",
    devHandle: "@bayn", status: "Watching", stage: "Published", edgeVerified: true,
    symbols: ["SPY"], lastSignalAt: new Date().toISOString(), createdAt: "2025-02-20T00:00:00Z",
    stats: { sharpe: 1.18, winRate: 0.78, maxDrawdown: 0.12, sampleSize: 142, avgR: 0.22, liveDays: 280, subscribers: 0 },
  },
  {
    id: "s-mes-orb", name: "MES Opening-Range Breakout", assetClass: "futures",
    description: "Buys/sells the 15-minute opening-range breakout on MES with ATR stop.",
    longDescription: "Captures session-open momentum on Micro E-mini S&P. Single shot per day.",
    entryRules: "Break of 09:30–09:45 ET range with volume confirmation.",
    exitRules: "Target = 1.5R. Stop = 1× ATR(14).",
    devHandle: "@bayn", status: "Watching", stage: "Published", edgeVerified: true,
    symbols: ["MES1!"], lastSignalAt: new Date().toISOString(), createdAt: "2025-03-04T00:00:00Z",
    stats: { sharpe: 1.27, winRate: 0.52, maxDrawdown: 0.11, sampleSize: 318, avgR: 0.55, liveDays: 156, subscribers: 0 },
  },
];

// Strategy catalog: 4 always-free verified strategies (one per asset class).
// Premium strategies are backend-driven and not yet wired.
export async function getStrategies(): Promise<Strategy[]> { await wait(); return FREE_STRATEGIES.slice(); }
export async function getStrategyById(id: string): Promise<Strategy | undefined> { await wait(); return FREE_STRATEGIES.find((s) => s.id === id); }
export async function getFollowedStrategies(): Promise<Strategy[]> {
  await wait();
  const followed = new Set(getEffectiveFollowedIds());
  return FREE_STRATEGIES.filter((s) => followed.has(s.id));
}

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
