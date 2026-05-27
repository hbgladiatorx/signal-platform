// Studio (developer-side) API. Mock now → Supabase later.
import {
  devStrategies, backtestRuns, personalSignals, studioEarnings, graphTemplates,
} from "../mockData";
import type { DevStrategy, BacktestRun, PersonalSignal, StrategyGraph } from "../types";

const wait = (ms = 120) => new Promise((r) => setTimeout(r, ms));

export async function getDevStrategies(): Promise<DevStrategy[]> {
  await wait();
  // TODO: supabase.from('dev_strategies').select('*').eq('user_id', userId)
  return devStrategies;
}

export async function getDevStrategy(id: string): Promise<DevStrategy | undefined> {
  await wait();
  return devStrategies.find((s) => s.id === id);
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

export async function runBacktest(_id: string, _params: BacktestRun["params"]) {
  await wait(900);
  // TODO: invoke backtest server function
  return { ok: true, runId: `bt-${Date.now()}` };
}

export async function deployStrategyLive(_id: string) {
  await wait(300);
  return { ok: true };
}

export async function submitStrategyToBayn(_id: string) {
  await wait(300);
  return { ok: true };
}
