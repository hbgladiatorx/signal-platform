// Studio (developer-side) API.
// Live state — no mock seeding. A developer only sees what they actually
// create. Drafts live in-memory for the session until a backend is wired.
import type { DevStrategy, BacktestRun, PersonalSignal, StrategyGraph, StudioEarning } from "../types";

const wait = (ms = 80) => new Promise((r) => setTimeout(r, ms));

const userStrategies: DevStrategy[] = [];
const userBacktests: BacktestRun[] = [];

export async function getDevStrategies(): Promise<DevStrategy[]> {
  await wait();
  return userStrategies.slice();
}

export async function getDevStrategy(id: string): Promise<DevStrategy | undefined> {
  await wait();
  return userStrategies.find((x) => x.id === id);
}

export function ensureDevStrategyDraft(input: {
  id?: string;
  name: string;
  assetClass: DevStrategy["assetClass"];
  graph: StrategyGraph;
}): DevStrategy {
  const existing = input.id ? userStrategies.find((s) => s.id === input.id) : undefined;
  if (existing) {
    existing.name = input.name;
    existing.assetClass = input.assetClass;
    existing.graph = input.graph;
    return existing;
  }
  const newId = `dev-${Date.now()}`;
  const now = new Date().toISOString();
  const draft: DevStrategy = {
    id: newId,
    name: input.name,
    description: "",
    assetClass: input.assetClass,
    stage: "Draft",
    createdAt: now,
    lastRunAt: now,
    graph: input.graph,
    liveSinceDays: 0,
    stats: { sharpe: 0, winRate: 0, maxDrawdown: 0, sampleSize: 0, avgR: 0, liveDays: 0, subscribers: 0 },
    versions: [{ id: "v1", createdAt: now, note: "Initial draft" }],
  };
  userStrategies.unshift(draft);
  return draft;
}

export async function getTemplates(): Promise<Array<{ id: string; name: string; description: string; assetClass: DevStrategy["assetClass"]; graph: StrategyGraph }>> { await wait(); return []; }

export async function getBacktestsForStrategy(strategyId: string): Promise<BacktestRun[]> {
  await wait();
  return userBacktests.filter((b) => b.strategyId === strategyId);
}

export async function getBacktest(id: string): Promise<BacktestRun | undefined> {
  await wait();
  return userBacktests.find((b) => b.id === id);
}

export async function getPersonalSignals(_opts?: { strategyId?: string; limit?: number }): Promise<PersonalSignal[]> {
  await wait();
  return [];
}

export async function getEarnings(): Promise<StudioEarning[]> {
  await wait();
  return [];
}

export async function saveStrategyGraph(_id: string, _graph: StrategyGraph) {
  await wait();
  return { ok: true, savedAt: new Date().toISOString() };
}

export async function runBacktest(strategyId: string, params: BacktestRun["params"]): Promise<BacktestRun> {
  // Real backtest engine is not implemented. Return a zeroed run so the UI
  // can render an explicit empty state — no synthetic equity curves.
  await wait();
  const now = new Date().toISOString();
  const run: BacktestRun = {
    id: `bt-${strategyId}-${Date.now()}`,
    strategyId,
    ranAt: now,
    params,
    stats: {
      totalReturn: 0, cagr: 0, sharpe: 0, sortino: 0, maxDrawdown: 0,
      winRate: 0, profitFactor: 0, avgWin: 0, avgLoss: 0, avgHoldDays: 0, totalTrades: 0,
    },
    equity: [],
    trades: [],
    monthlyReturns: [],
  };
  userBacktests.unshift(run);
  return run;
}

export async function deployStrategyLive(_id: string) { await wait(); return { ok: true }; }
export async function submitStrategyToBayn(_id: string) { await wait(); return { ok: true }; }
