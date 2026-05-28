// Studio (developer-side) API. Mock now → Supabase later.
import {
  devStrategies, backtestRuns, personalSignals, studioEarnings, graphTemplates,
} from "../mockData";
import { getStudioSeeded, setStudioSeeded } from "../user-prefs";
import type { DevStrategy, BacktestRun, PersonalSignal, StrategyGraph } from "../types";

const wait = (ms = 120) => new Promise((r) => setTimeout(r, ms));

/** A "user-created" strategy is any draft saved during this session.
 *  We mark those with an id beginning with `dev-` (see ensureDevStrategyDraft).
 *  Mock seed strategies use other ids and are hidden until studio is seeded. */
const isUserCreated = (id: string) => id.startsWith("dev-");

export async function getDevStrategies(): Promise<DevStrategy[]> {
  await wait();
  if (getStudioSeeded()) return devStrategies;
  return devStrategies.filter((s) => isUserCreated(s.id));
}

export async function getDevStrategy(id: string): Promise<DevStrategy | undefined> {
  await wait();
  const s = devStrategies.find((x) => x.id === id);
  if (!s) return undefined;
  if (!getStudioSeeded() && !isUserCreated(s.id)) return undefined;
  return s;
}


export function ensureDevStrategyDraft(input: {
  id?: string;
  name: string;
  assetClass: DevStrategy["assetClass"];
  graph: StrategyGraph;
}): DevStrategy {
  const existing = input.id ? devStrategies.find((s) => s.id === input.id) : undefined;
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
  devStrategies.unshift(draft);
  return draft;
}

export async function getTemplates() {
  await wait(60);
  return graphTemplates;
}

export async function getBacktestsForStrategy(strategyId: string): Promise<BacktestRun[]> {
  await wait();
  return backtestRuns.filter((b) => b.strategyId === strategyId);
}

export async function getBacktest(id: string): Promise<BacktestRun | undefined> {
  await wait();
  return backtestRuns.find((b) => b.id === id);
}

export async function getPersonalSignals(opts?: { strategyId?: string; limit?: number }): Promise<PersonalSignal[]> {
  await wait();
  let list = [...personalSignals].sort((a, b) => +new Date(b.firedAt) - +new Date(a.firedAt));
  if (opts?.strategyId) list = list.filter((s) => s.ownStrategyId === opts.strategyId);
  if (opts?.limit) list = list.slice(0, opts.limit);
  return list;
}

export async function getEarnings() {
  await wait();
  return studioEarnings;
}

export async function saveStrategyGraph(_id: string, _graph: StrategyGraph) {
  await wait(220);
  // TODO: supabase.from('dev_strategies').update({ graph }).eq('id', _id)
  return { ok: true, savedAt: new Date().toISOString() };
}

export async function runBacktest(strategyId: string, params: BacktestRun["params"]): Promise<BacktestRun> {
  await wait(900);
  const run = synthesizeBacktestRun(strategyId, params);
  backtestRuns.unshift(run);
  return run;
}

function synthesizeBacktestRun(strategyId: string, params: BacktestRun["params"]): BacktestRun {
  const start = new Date(params.startDate).getTime();
  const end = new Date(params.endDate).getTime();
  const days = Math.max(30, Math.floor((end - start) / 86_400_000));
  // equity walk
  const equity: BacktestRun["equity"] = [];
  let v = params.capital;
  const drift = 0.0006 + Math.random() * 0.0006;
  const vol = 0.012 + Math.random() * 0.006;
  for (let i = 0; i <= days; i++) {
    const r = drift + (Math.random() - 0.5) * vol;
    v = Math.max(v * (1 + r), params.capital * 0.4);
    equity.push({ t: new Date(start + i * 86_400_000).toISOString(), equity: +v.toFixed(2) });
  }
  const totalReturn = (v - params.capital) / params.capital;
  // monthly
  const monthly: Record<string, { first: number; last: number }> = {};
  for (const p of equity) {
    const k = p.t.slice(0, 7);
    monthly[k] ??= { first: p.equity, last: p.equity };
    monthly[k].last = p.equity;
  }
  const monthlyReturns = Object.entries(monthly).map(([month, m]) => ({ month: month.slice(2), ret: (m.last - m.first) / m.first }));
  // trades
  const tradeCount = Math.max(20, Math.floor(days / 6));
  const symbols = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "BTC", "ETH"];
  const trades: BacktestRun["trades"] = Array.from({ length: tradeCount }).map((_, i) => {
    const pnlR = +(Math.random() * 3.6 - 1.4).toFixed(2);
    const pnlPct = +(pnlR * 0.01).toFixed(4);
    const entryDate = new Date(start + (i / tradeCount) * (end - start)).toISOString();
    const exitDate = new Date(+new Date(entryDate) + (1 + Math.random() * 5) * 86_400_000).toISOString();
    const entry = +(50 + Math.random() * 400).toFixed(2);
    return {
      id: `t-${strategyId}-${i}-${Date.now().toString(36)}`,
      entryDate, exitDate,
      symbol: symbols[i % symbols.length],
      direction: Math.random() > 0.35 ? "LONG" : "SHORT",
      entry, exit: +(entry * (1 + pnlPct)).toFixed(2),
      pnlPct, pnlR,
    };
  });
  const wins = trades.filter((t) => t.pnlR > 0);
  const losses = trades.filter((t) => t.pnlR <= 0);
  const sumWin = wins.reduce((a, t) => a + t.pnlR, 0);
  const sumLoss = Math.abs(losses.reduce((a, t) => a + t.pnlR, 0)) || 1;
  // drawdown
  let peak = equity[0].equity, maxDD = 0;
  for (const p of equity) { peak = Math.max(peak, p.equity); maxDD = Math.min(maxDD, (p.equity - peak) / peak); }
  const yrs = days / 365;
  const cagr = Math.pow(1 + totalReturn, 1 / Math.max(yrs, 0.25)) - 1;
  return {
    id: `bt-${strategyId}-${Date.now()}`,
    strategyId,
    ranAt: new Date().toISOString(),
    params,
    stats: {
      totalReturn,
      cagr,
      sharpe: +(1.1 + Math.random() * 1.2).toFixed(2),
      sortino: +(1.4 + Math.random() * 1.4).toFixed(2),
      maxDrawdown: maxDD,
      winRate: wins.length / trades.length,
      profitFactor: +(sumWin / sumLoss).toFixed(2),
      avgWin: +(sumWin / Math.max(wins.length, 1)).toFixed(2),
      avgLoss: +(losses.reduce((a, t) => a + t.pnlR, 0) / Math.max(losses.length, 1)).toFixed(2),
      avgHoldDays: 3,
      totalTrades: trades.length,
    },
    equity,
    trades,
    monthlyReturns,
  };
}

export async function deployStrategyLive(_id: string) {
  await wait(300);
  return { ok: true };
}

export async function submitStrategyToBayn(_id: string) {
  await wait(300);
  return { ok: true };
}
