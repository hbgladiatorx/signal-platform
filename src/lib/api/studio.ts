// Studio (developer-side) API — wired to the signal-platform FastAPI backend.
//
// Strategies map to /user-strategies (+ built-ins from /strategies, surfaced
// read-only with a "builtin:" id so they're immediately runnable). Backtests
// map to /backtests (+ /trades, /equity). Per the locked plan, the visual
// graph is persisted on the user_strategy (graph_json) but the *runnable*
// artifact is Python source generated from the graph via /user-strategies/
// translate (LLM). Marketplace-side concerns (personal signals, earnings,
// deploy/submit) remain stubbed until Phase 3/4.
import { api, ApiError } from "@/lib/api/client";
import type {
  AssetClass,
  BacktestRun,
  DevStrategy,
  Direction,
  EquityPoint,
  PersonalSignal,
  PipelineStage,
  StrategyGraph,
  StudioEarning,
} from "../types";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const BUILTIN_PREFIX = "builtin:";

// ---------- backend wire types (subset we consume) ----------
interface ApiUserStrategy {
  id: string;
  name: string;
  description?: string | null;
  class_name: string;
  params_schema: Record<string, unknown>;
  graph_json?: StrategyGraph | null;
  asset_class?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  source_code?: string;
  nl_description?: string | null;
}
interface ApiStrategyInfo {
  name: string;
  description: string;
  params_schema: Record<string, unknown>;
  source: "built-in" | "user";
  user_strategy_id?: string | null;
}
interface ApiInstrument {
  id: number;
  asset_class: string;
  canonical_symbol: string;
  venue: string;
  active: boolean;
}
interface ApiBacktestSummary {
  id: string;
  strategy_name: string;
  symbols: string[];
  bar_resolution: string;
  status: "pending" | "running" | "completed" | "failed";
  created_at: string;
  completed_at?: string | null;
  bars_start?: string | null;
  bars_end?: string | null;
  total_return_pct?: number | null;
  sharpe_ratio?: number | null;
  max_drawdown_pct?: number | null;
  num_closed_trades?: number | null;
  win_rate_pct?: number | null;
}
interface ApiBacktestDetail extends ApiBacktestSummary {
  params_json?: Record<string, unknown>;
  starting_cash?: number | string | null;
  fee_rate_bps?: number | null;
  slippage_bps?: number | null;
  error_message?: string | null;
  annualized_return_pct?: number | null;
  sortino_ratio?: number | null;
  calmar_ratio?: number | null;
  profit_factor?: number | null;
}
interface ApiTradeRow {
  symbol: string;
  side: string;
  entry_ts: string;
  exit_ts: string;
  entry_avg_price: number;
  exit_avg_price: number;
  quantity: number;
  gross_pnl: number;
  fees: number;
  net_pnl: number;
  duration_seconds: number;
}
interface ApiEquityRow {
  ts: string;
  cash: number;
  positions_value: number;
  total_equity: number;
}

// ---------- helpers ----------
const pct = (v?: number | null) => (v ?? 0) / 100; // backend percent -> fraction
const num = (v: unknown) => (typeof v === "number" ? v : Number(v) || 0);

const ASSET_TO_VENUE_CLASS: Record<string, string> = {
  crypto: "crypto_spot",
  stocks: "equity",
  options: "option",
  futures: "equity",
};

function toAssetClass(s?: string | null): AssetClass {
  if (s === "crypto" || s === "stocks" || s === "options" || s === "futures") return s;
  if (s === "crypto_spot") return "crypto";
  if (s === "equity") return "stocks";
  if (s === "option") return "options";
  return "stocks";
}

function userToDev(u: ApiUserStrategy): DevStrategy {
  return {
    id: u.id,
    name: u.name,
    description: u.description ?? "",
    assetClass: toAssetClass(u.asset_class),
    stage: "Draft",
    createdAt: u.created_at,
    lastRunAt: u.updated_at,
    graph: u.graph_json ?? { nodes: [], edges: [] },
    versions: [{ id: "v1", createdAt: u.created_at, note: "Saved" }],
  };
}

function builtinToDev(s: ApiStrategyInfo): DevStrategy {
  const now = new Date().toISOString();
  return {
    id: `${BUILTIN_PREFIX}${s.name}`,
    name: s.name,
    description: s.description,
    assetClass: "crypto",
    stage: "Live",
    createdAt: now,
    lastRunAt: now,
    graph: { nodes: [], edges: [] },
    versions: [{ id: "v1", createdAt: now, note: "Built-in strategy" }],
  };
}

function summaryToRun(s: ApiBacktestSummary, strategyId: string): BacktestRun {
  return {
    id: s.id,
    strategyId,
    ranAt: s.completed_at ?? s.created_at,
    params: {
      startDate: (s.bars_start ?? "").slice(0, 10),
      endDate: (s.bars_end ?? "").slice(0, 10),
      capital: 0,
      commissionBps: 0,
      slippageBps: 0,
    },
    stats: {
      totalReturn: pct(s.total_return_pct),
      cagr: 0,
      sharpe: s.sharpe_ratio ?? 0,
      sortino: 0,
      maxDrawdown: pct(s.max_drawdown_pct),
      winRate: pct(s.win_rate_pct),
      profitFactor: 0,
      avgWin: 0,
      avgLoss: 0,
      avgHoldDays: 0,
      totalTrades: s.num_closed_trades ?? 0,
    },
    equity: [],
    trades: [],
    monthlyReturns: [],
  };
}

function monthlyReturns(equity: EquityPoint[]): Array<{ month: string; ret: number }> {
  const byMonth = new Map<string, { first: number; last: number }>();
  for (const p of equity) {
    const month = p.t.slice(0, 7);
    const cur = byMonth.get(month);
    if (!cur) byMonth.set(month, { first: p.equity, last: p.equity });
    else cur.last = p.equity;
  }
  return [...byMonth.entries()].map(([month, { first, last }]) => ({
    month,
    ret: first ? last / first - 1 : 0,
  }));
}

function detailToRun(
  d: ApiBacktestDetail,
  trades: ApiTradeRow[],
  equityRows: ApiEquityRow[],
  strategyId: string,
): BacktestRun {
  const equity: EquityPoint[] = equityRows.map((e) => ({ t: e.ts, equity: e.total_equity }));
  const mappedTrades = trades.map((t, i) => {
    const cost = t.entry_avg_price * t.quantity;
    const pnlPct = cost ? t.net_pnl / cost : 0;
    return {
      id: `${d.id}-${i}`,
      entryDate: t.entry_ts,
      exitDate: t.exit_ts,
      symbol: t.symbol,
      direction: (t.side?.toLowerCase() === "sell" ? "SHORT" : "LONG") as Direction,
      entry: t.entry_avg_price,
      exit: t.exit_avg_price,
      pnlPct,
      pnlR: pnlPct, // backend tracks no risk unit; pnl fraction stands in for R
    };
  });
  const wins = mappedTrades.filter((t) => t.pnlPct > 0);
  const losses = mappedTrades.filter((t) => t.pnlPct < 0);
  const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
  const avgHoldDays = trades.length
    ? avg(trades.map((t) => t.duration_seconds)) / 86_400
    : 0;
  return {
    id: d.id,
    strategyId,
    ranAt: d.completed_at ?? d.created_at,
    params: {
      startDate: (d.bars_start ?? "").slice(0, 10),
      endDate: (d.bars_end ?? "").slice(0, 10),
      capital: num(d.starting_cash),
      commissionBps: d.fee_rate_bps ?? 0,
      slippageBps: d.slippage_bps ?? 0,
    },
    stats: {
      totalReturn: pct(d.total_return_pct),
      cagr: pct(d.annualized_return_pct),
      sharpe: d.sharpe_ratio ?? 0,
      sortino: d.sortino_ratio ?? 0,
      maxDrawdown: pct(d.max_drawdown_pct),
      winRate: pct(d.win_rate_pct),
      profitFactor: d.profit_factor ?? 0,
      avgWin: avg(wins.map((t) => t.pnlR)),
      avgLoss: avg(losses.map((t) => t.pnlR)),
      avgHoldDays: Math.round(avgHoldDays * 10) / 10,
      totalTrades: d.num_closed_trades ?? mappedTrades.length,
    },
    equity,
    trades: mappedTrades,
    monthlyReturns: monthlyReturns(equity),
  };
}

async function strategyNameForId(strategyId: string): Promise<string> {
  if (strategyId.startsWith(BUILTIN_PREFIX)) return strategyId.slice(BUILTIN_PREFIX.length);
  const s = await api.get<ApiUserStrategy>(`/user-strategies/${strategyId}`);
  return s.name;
}

async function resolveSymbols(graph: StrategyGraph, assetClass: AssetClass): Promise<string[]> {
  const instruments = await api.get<ApiInstrument[]>("/instruments", { active: true });
  const canonical = new Set(instruments.map((i) => i.canonical_symbol));
  // Prefer symbols referenced in the graph that actually exist as instruments.
  const fromGraph: string[] = [];
  for (const node of graph.nodes ?? []) {
    for (const v of Object.values(node.data ?? {})) {
      if (typeof v === "string" && canonical.has(v)) fromGraph.push(v);
      if (Array.isArray(v)) for (const x of v) if (typeof x === "string" && canonical.has(x)) fromGraph.push(x);
    }
  }
  if (fromGraph.length) return [...new Set(fromGraph)];
  const wantClass = ASSET_TO_VENUE_CLASS[assetClass];
  const preferred = instruments.filter((i) => i.asset_class === wantClass);
  const pick = preferred[0] ?? instruments[0];
  return pick ? [pick.canonical_symbol] : [];
}

// Serialize a reactflow graph into a natural-language spec for the LLM
// translator (the locked graph->code bridge). Lossy by design.
function graphToNL(name: string, assetClass: AssetClass, graph: StrategyGraph): string {
  const lines: string[] = [
    `Build a ${assetClass} trading strategy named "${name}".`,
  ];
  const nodes = graph.nodes ?? [];
  if (nodes.length) {
    lines.push("It is composed of these building blocks:");
    for (const n of nodes) {
      const cfg = Object.entries(n.data ?? {})
        .filter(([, v]) => v !== null && v !== undefined && v !== "")
        .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("/") : String(v)}`)
        .join(", ");
      lines.push(`- ${n.label} [${n.category}/${n.type}]${cfg ? ` (${cfg})` : ""}`);
    }
    if (graph.edges?.length) {
      lines.push(`Wiring: ${graph.edges.map((e) => `${e.source}->${e.target}`).join(", ")}.`);
    }
  } else {
    lines.push("Use a simple, sensible default rule set for this asset class.");
  }
  return lines.join("\n");
}

// ============================================================
// Strategies
// ============================================================

export async function getDevStrategies(): Promise<DevStrategy[]> {
  const [users, builtins] = await Promise.all([
    api.get<ApiUserStrategy[]>("/user-strategies", { limit: 200 }),
    api.get<ApiStrategyInfo[]>("/strategies").catch(() => [] as ApiStrategyInfo[]),
  ]);
  const userDevs = users.map(userToDev);
  const builtinDevs = builtins
    .filter((s) => s.source === "built-in")
    .map(builtinToDev);
  return [...userDevs, ...builtinDevs];
}

export async function getDevStrategy(id: string): Promise<DevStrategy | undefined> {
  if (!id || id === "new") return undefined;
  if (id.startsWith(BUILTIN_PREFIX)) {
    const name = id.slice(BUILTIN_PREFIX.length);
    const s = await api.get<ApiStrategyInfo>(`/strategies/${encodeURIComponent(name)}`);
    return builtinToDev(s);
  }
  try {
    const u = await api.get<ApiUserStrategy>(`/user-strategies/${id}`);
    return userToDev(u);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return undefined;
    throw e;
  }
}

export async function getTemplates(): Promise<
  Array<{ id: string; name: string; description: string; assetClass: AssetClass; graph: StrategyGraph }>
> {
  const builtins = await api.get<ApiStrategyInfo[]>("/strategies").catch(() => [] as ApiStrategyInfo[]);
  return builtins
    .filter((s) => s.source === "built-in")
    .map((s) => ({
      id: `${BUILTIN_PREFIX}${s.name}`,
      name: s.name,
      description: s.description,
      assetClass: "crypto" as AssetClass,
      graph: { nodes: [], edges: [] },
    }));
}

// Translate the graph to runnable source and create/update the user_strategy.
// Async (was synchronous against the in-memory mock) — the one builder call
// site awaits it.
export async function ensureDevStrategyDraft(input: {
  id?: string;
  name: string;
  assetClass: AssetClass;
  graph: StrategyGraph;
}): Promise<DevStrategy> {
  const nl = graphToNL(input.name, input.assetClass, input.graph);
  const translated = await api.post<{
    ok: boolean;
    source_code?: string;
    llm_error?: string;
    validation_errors?: Array<Record<string, unknown>>;
  }>("/user-strategies/translate", { nl_description: nl });

  if (!translated.ok || !translated.source_code) {
    const why =
      translated.llm_error ||
      (translated.validation_errors?.length
        ? `validation failed (${translated.validation_errors.length} issue(s))`
        : "translation failed");
    throw new ApiError(422, `Couldn't generate runnable code from the graph: ${why}`);
  }

  const body = {
    name: input.name,
    description: "",
    nl_description: nl,
    source_code: translated.source_code,
    graph_json: input.graph,
    asset_class: input.assetClass,
  };

  // Update existing, or create — falling back to update-by-name on 409.
  if (input.id && !input.id.startsWith(BUILTIN_PREFIX)) {
    const u = await api.put<ApiUserStrategy>(`/user-strategies/${input.id}`, body);
    return userToDev(u);
  }
  try {
    const created = await api.post<{ id: string }>("/user-strategies", body);
    const u = await api.get<ApiUserStrategy>(`/user-strategies/${created.id}`);
    return userToDev(u);
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      const all = await api.get<ApiUserStrategy[]>("/user-strategies", { limit: 200 });
      const existing = all.find((s) => s.name === input.name);
      if (existing) {
        const u = await api.put<ApiUserStrategy>(`/user-strategies/${existing.id}`, body);
        return userToDev(u);
      }
    }
    throw e;
  }
}

export async function saveStrategyGraph(id: string, graph: StrategyGraph) {
  // Reuse the same translate+persist path. For a "new" id, create on save.
  const existing = id && id !== "new" ? await getDevStrategy(id) : undefined;
  await ensureDevStrategyDraft({
    id: existing?.id,
    name: existing?.name ?? `Strategy ${new Date().toISOString().slice(0, 10)}`,
    assetClass: existing?.assetClass ?? "crypto",
    graph,
  });
  return { ok: true, savedAt: new Date().toISOString() };
}

// ============================================================
// Backtests
// ============================================================

export async function getBacktestsForStrategy(strategyId: string): Promise<BacktestRun[]> {
  const name = await strategyNameForId(strategyId);
  const list = await api.get<ApiBacktestSummary[]>("/backtests", { limit: 100 });
  return list
    .filter((b) => b.strategy_name === name)
    .map((b) => summaryToRun(b, strategyId));
}

export async function getBacktest(id: string): Promise<BacktestRun | undefined> {
  try {
    const detail = await api.get<ApiBacktestDetail>(`/backtests/${id}`);
    const [trades, equity] = await Promise.all([
      api.get<ApiTradeRow[]>(`/backtests/${id}/trades`).catch(() => [] as ApiTradeRow[]),
      api.get<ApiEquityRow[]>(`/backtests/${id}/equity`).catch(() => [] as ApiEquityRow[]),
    ]);
    return detailToRun(detail, trades, equity, id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return undefined;
    throw e;
  }
}

export async function runBacktest(
  strategyId: string,
  params: BacktestRun["params"],
): Promise<BacktestRun> {
  let name: string;
  let graph: StrategyGraph = { nodes: [], edges: [] };
  let assetClass: AssetClass = "crypto";
  if (strategyId.startsWith(BUILTIN_PREFIX)) {
    name = strategyId.slice(BUILTIN_PREFIX.length);
  } else {
    const s = await api.get<ApiUserStrategy>(`/user-strategies/${strategyId}`);
    name = s.name;
    graph = s.graph_json ?? graph;
    assetClass = toAssetClass(s.asset_class);
  }

  const symbols = await resolveSymbols(graph, assetClass);
  if (symbols.length === 0) {
    throw new ApiError(422, "No tradable instruments are available to backtest against.");
  }

  const { id } = await api.post<{ id: string; status: string }>("/backtests", {
    strategy_name: name,
    params: {},
    symbols,
    bar_resolution: "1h",
    starting_cash: params.capital > 0 ? params.capital : 10000,
    fee_rate_bps: Math.round(params.commissionBps) || 10,
    slippage_bps: Math.round(params.slippageBps) || 5,
  });

  // Poll the async job to completion (the UI shows a loading toast meanwhile).
  for (let i = 0; i < 150; i++) {
    const d = await api.get<ApiBacktestDetail>(`/backtests/${id}`);
    if (d.status === "completed") {
      const full = await getBacktest(id);
      if (full) return full;
    }
    if (d.status === "failed") {
      throw new ApiError(500, d.error_message || "Backtest failed");
    }
    await sleep(2000);
  }
  throw new ApiError(504, "Backtest timed out while waiting for results.");
}

// ============================================================
// Marketplace-side (Phase 3/4) — still stubbed
// ============================================================

export async function getPersonalSignals(_opts?: { strategyId?: string; limit?: number }): Promise<PersonalSignal[]> {
  return [];
}

export async function getEarnings(): Promise<StudioEarning[]> {
  return [];
}

export async function deployStrategyLive(_id: string) {
  // Phase 3: will start a paper/live session via /paper-sessions.
  return { ok: true };
}

export async function submitStrategyToBayn(_id: string) {
  // Phase 4: marketplace submission.
  return { ok: true };
}

// Keep the PipelineStage type referenced so future stage mapping stays typed.
export type { PipelineStage };
