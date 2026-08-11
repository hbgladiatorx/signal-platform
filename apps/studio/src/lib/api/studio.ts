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
import { createSession } from "@/lib/api/sessions";
import { listApiCredentials, listPlatformCredentials } from "@/lib/api/settings";
import type {
  AssetClass,
  BacktestAnalysis,
  BacktestAttribution,
  BacktestMlModel,
  BacktestRun,
  DevStrategy,
  Direction,
  EquityPoint,
  PersonalSignal,
  PipelineStage,
  StrategyGraph,
  StrategyStats,
  StudioEarning,
  SuggestTweaksResult,
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
  profit_factor?: number | null;
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
  attribution?: BacktestAttribution | null;
  ml_model?: BacktestMlModel | null;
  analysis?: BacktestAnalysis | null;
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

// Pick the "headline" backtest for a strategy: the completed run with the
// widest tested window (full-period over H1/H2 splits), tie-broken by trade
// count. This is what we surface as the strategy's performance in the list.
function pickHeadline(bts: ApiBacktestSummary[]): ApiBacktestSummary | undefined {
  const span = (b: ApiBacktestSummary) =>
    b.bars_start && b.bars_end
      ? new Date(b.bars_end).getTime() - new Date(b.bars_start).getTime()
      : 0;
  return bts
    .filter((b) => b.status === "completed" && (b.num_closed_trades ?? 0) > 0)
    .slice()
    .sort((a, b) => span(b) - span(a) || (b.num_closed_trades ?? 0) - (a.num_closed_trades ?? 0))[0];
}

function statsFromBacktest(b: ApiBacktestSummary): StrategyStats {
  return {
    sharpe: b.sharpe_ratio ?? 0,
    winRate: (b.win_rate_pct ?? 0) / 100,
    maxDrawdown: (b.max_drawdown_pct ?? 0) / 100,
    sampleSize: b.num_closed_trades ?? 0,
    avgR: 0,
    liveDays: 0,
    subscribers: 0,
    totalReturn: (b.total_return_pct ?? 0) / 100,
    profitFactor: b.profit_factor ?? undefined,
    totalTrades: b.num_closed_trades ?? 0,
  };
}

function userToDev(u: ApiUserStrategy, bts: ApiBacktestSummary[] = []): DevStrategy {
  const head = pickHeadline(bts);
  const latest = bts.length
    ? bts.slice().sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      )[0]
    : undefined;
  return {
    id: u.id,
    name: u.name,
    description: u.description ?? "",
    nlDescription: u.nl_description ?? undefined,
    assetClass: toAssetClass(u.asset_class),
    // Reflect reality: a strategy with a completed backtest has been backtested;
    // otherwise it's still a draft. (Live trading is tracked separately.)
    stage: head ? "Backtested" : "Draft",
    isActive: u.is_active,
    createdAt: u.created_at,
    lastRunAt: latest?.created_at ?? u.updated_at,
    graph: u.graph_json ?? { nodes: [], edges: [] },
    sourceCode: u.source_code,
    stats: head ? statsFromBacktest(head) : undefined,
    headlineBarResolution: head?.bar_resolution
      ? normalizeBarResolution(head.bar_resolution) : undefined,
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
    symbols: s.symbols ?? [],
    barResolution: s.bar_resolution,
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
  // Backend serializes Postgres NUMERIC columns as strings (and may send null),
  // so coerce every numeric field before it reaches `.toFixed`/arithmetic.
  const num = (v: unknown): number => {
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) ? n : 0;
  };
  const equity: EquityPoint[] = equityRows.map((e) => ({ t: e.ts, equity: num(e.total_equity) }));
  const mappedTrades = trades.map((t, i) => {
    const entry = num(t.entry_avg_price);
    const exit = num(t.exit_avg_price);
    const cost = entry * num(t.quantity);
    const pnlPct = cost ? num(t.net_pnl) / cost : 0;
    return {
      id: `${d.id}-${i}`,
      entryDate: t.entry_ts,
      exitDate: t.exit_ts,
      symbol: t.symbol,
      direction: (t.side?.toLowerCase() === "sell" ? "SHORT" : "LONG") as Direction,
      entry,
      exit,
      pnlPct,
      pnlR: pnlPct, // backend tracks no risk unit; pnl fraction stands in for R
    };
  });
  const wins = mappedTrades.filter((t) => t.pnlPct > 0);
  const losses = mappedTrades.filter((t) => t.pnlPct < 0);
  const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
  const avgHoldDays = trades.length
    ? avg(trades.map((t) => num(t.duration_seconds))) / 86_400
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
    symbols: d.symbols ?? [],
    barResolution: d.bar_resolution,
    attribution: d.attribution ?? null,
    mlModel: d.ml_model ?? null,
    analysis: d.analysis ?? null,
  };
}

async function strategyNameForId(strategyId: string): Promise<string> {
  if (strategyId.startsWith(BUILTIN_PREFIX)) return strategyId.slice(BUILTIN_PREFIX.length);
  const s = await api.get<ApiUserStrategy>(`/user-strategies/${strategyId}`);
  return s.name;
}

// Bare ticker of a canonical symbol: "BTC-USDT@BINANCEUS" -> "BTC",
// "SPY@ALPACA" -> "SPY", "BTC-PERP" -> "BTC". Used to match a strategy's
// intended symbol to a real, data-bearing instrument.
const baseTicker = (s: string) => s.split("@")[0].split(/[-/]/)[0].toUpperCase();

async function resolveSymbols(graph: StrategyGraph, assetClass: AssetClass): Promise<string[]> {
  // Coverage-sorted options for this asset class (most history first). Prefer
  // instruments that actually have data — backtesting a no-data symbol (the old
  // alphabetical fallback landed on 1000MOG-USDT for BTC strategies) yields zero
  // trades, which is exactly the "not actually backtesting" bug.
  const opts = await getInstrumentsForAsset(assetClass);
  const withData = opts.filter((o) => o.bars > 0);
  const pool = withData.length ? withData : opts;
  const bySymbol = new Map(opts.map((o) => [o.symbol, o]));

  // Collect every string the graph references (the price node's symbol, etc.).
  const wanted: string[] = [];
  for (const node of graph.nodes ?? []) {
    for (const v of Object.values(node.data ?? {})) {
      if (typeof v === "string") wanted.push(v);
      else if (Array.isArray(v)) for (const x of v) if (typeof x === "string") wanted.push(x);
    }
  }

  const resolveOne = (raw: string): string | undefined => {
    if (bySymbol.has(raw)) return raw; // already a canonical symbol
    // Otherwise match by base ticker to the highest-coverage instrument of that
    // base (e.g. "BTC-PERP"/"BTC" -> BTC-USDT@BINANCEUS, the one with 9k bars).
    const base = baseTicker(raw);
    if (base.length < 2) return undefined; // skip noise like "1m", ">", "5"
    const match = pool.find((o) => baseTicker(o.symbol) === base);
    return match?.symbol;
  };

  const resolved: string[] = [];
  for (const w of wanted) {
    const r = resolveOne(w);
    if (r) resolved.push(r);
  }
  if (resolved.length) return [...new Set(resolved)];
  // Nothing in the graph matched a real instrument — fall back to the single
  // highest-coverage instrument of this asset class (never a no-data altcoin).
  return pool.length ? [pool[0].symbol] : [];
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
  const [users, backtests] = await Promise.all([
    api.get<ApiUserStrategy[]>("/user-strategies", { limit: 200 }),
    api.get<ApiBacktestSummary[]>("/backtests", { limit: 100 }).catch(() => [] as ApiBacktestSummary[]),
  ]);
  const byName = new Map<string, ApiBacktestSummary[]>();
  for (const b of backtests) {
    const arr = byName.get(b.strategy_name);
    if (arr) arr.push(b);
    else byName.set(b.strategy_name, [b]);
  }
  // Built-in example strategies are intentionally excluded — Studio lists only
  // the user's own strategies.
  return users.map((u) => userToDev(u, byName.get(u.name) ?? []));
}

// Like getDevStrategies, but ALSO includes built-in strategies that have backtest
// runs — so the Backtests "View all" page shows every strategy with history, not
// only the user's own (built-in rows are read-only there). Keeps the per-run
// dashboard and the per-strategy page consistent.
export async function getBacktestStrategies(): Promise<DevStrategy[]> {
  const [users, builtins, backtests] = await Promise.all([
    api.get<ApiUserStrategy[]>("/user-strategies", { limit: 200 }),
    api.get<ApiStrategyInfo[]>("/strategies").catch(() => [] as ApiStrategyInfo[]),
    api.get<ApiBacktestSummary[]>("/backtests", { limit: 100 }).catch(() => [] as ApiBacktestSummary[]),
  ]);
  const byName = new Map<string, ApiBacktestSummary[]>();
  for (const b of backtests) {
    const arr = byName.get(b.strategy_name);
    if (arr) arr.push(b);
    else byName.set(b.strategy_name, [b]);
  }
  const userNames = new Set(users.map((u) => u.name));
  const userDevs = users.map((u) => userToDev(u, byName.get(u.name) ?? []));
  // Built-ins that actually have runs and aren't shadowed by a same-named user
  // strategy. Rendered read-only (no edit/delete) on the Backtests page.
  const builtinDevs = builtins
    .filter((s) => s.source === "built-in" && byName.has(s.name) && !userNames.has(s.name))
    .map((s) => builtinToDev(s));
  return [...userDevs, ...builtinDevs];
}

// Names of built-in strategies, so callers can tell a built-in run apart from a
// run whose (user) strategy was truly deleted.
export async function getBuiltinStrategyNames(): Promise<string[]> {
  const b = await api
    .get<ApiStrategyInfo[]>("/strategies")
    .catch(() => [] as ApiStrategyInfo[]);
  return b.filter((s) => s.source === "built-in").map((s) => s.name);
}

export async function getDevStrategy(id: string): Promise<DevStrategy | undefined> {
  if (!id || id === "new") return undefined;
  if (id.startsWith(BUILTIN_PREFIX)) {
    const name = id.slice(BUILTIN_PREFIX.length);
    const s = await api.get<ApiStrategyInfo>(`/strategies/${encodeURIComponent(name)}`);
    return builtinToDev(s);
  }
  try {
    const [u, backtests] = await Promise.all([
      api.get<ApiUserStrategy>(`/user-strategies/${id}`),
      api.get<ApiBacktestSummary[]>("/backtests", { limit: 100 }).catch(() => [] as ApiBacktestSummary[]),
    ]);
    return userToDev(u, backtests.filter((b) => b.strategy_name === u.name));
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return undefined;
    throw e;
  }
}

// Built-in strategies are served read-only from /strategies under a synthetic
// "builtin:" id — they have no /user-strategies row, so they can't be deleted.
export function isBuiltinStrategy(id: string): boolean {
  return id.startsWith(BUILTIN_PREFIX);
}

// The strategyId a built-in strategy's backtest history lives under (the detail
// route + getBacktestsForStrategy both understand this prefix).
export function builtinStrategyId(name: string): string {
  return `${BUILTIN_PREFIX}${name}`;
}

// Owner-scoped delete (204). The backend 404s a missing or foreign row, which
// surfaces here as ApiError(404).
export async function deleteUserStrategy(id: string): Promise<void> {
  if (isBuiltinStrategy(id)) {
    throw new ApiError(400, "Built-in strategies can't be deleted.");
  }
  await api.del<void>(`/user-strategies/${id}`);
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

  // LLM-free fast path: if we're updating an existing strategy whose stored
  // graph already matches and which already has generated source, skip the
  // /translate call entirely (it costs an Anthropic request). This lets an
  // already-built strategy re-run — and param-only re-runs work — without
  // depending on the LLM. We only re-translate when the graph actually changed.
  if (input.id && !input.id.startsWith(BUILTIN_PREFIX)) {
    try {
      const existing = await api.get<ApiUserStrategy>(`/user-strategies/${input.id}`);
      const sameGraph =
        JSON.stringify(existing.graph_json ?? null) === JSON.stringify(input.graph ?? null);
      if (sameGraph && existing.source_code) {
        // Keep name/asset in sync without touching source.
        if (existing.name !== input.name || existing.asset_class !== input.assetClass) {
          const u = await api.put<ApiUserStrategy>(`/user-strategies/${input.id}`, {
            name: input.name,
            asset_class: input.assetClass,
          });
          return userToDev(u);
        }
        return userToDev(existing);
      }
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) throw e;
      // 404 -> fall through to create.
    }
  }

  const translated = await api.post<{
    ok: boolean;
    source_code?: string;
    llm_error?: string;
    validation_errors?: Array<Record<string, unknown>>;
  }>("/user-strategies/translate", {
    nl_description: nl,
    // Send the structured graph so the backend can compile it deterministically
    // (honouring every entry/exit/risk node) instead of relying on the LLM.
    graph_json: input.graph,
    strategy_name: input.name,
    asset_class: input.assetClass,
  });

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

// ---------- code-first authoring (Python is the source of truth) ----------

export interface SourceValidation {
  ok: boolean;
  className?: string;
  errors: Array<{ line?: number; message: string }>;
}

// Validate Python strategy source WITHOUT saving — drives the live "valid/invalid"
// indicator as the user edits code in the builder.
export async function validateStrategySource(source: string): Promise<SourceValidation> {
  const r = await api.post<{
    ok: boolean;
    class_name?: string | null;
    errors?: Array<{ line?: number | null; message: string }>;
  }>("/user-strategies/validate", { source_code: source });
  return {
    ok: r.ok,
    className: r.class_name ?? undefined,
    errors: (r.errors ?? []).map((e) => ({ line: e.line ?? undefined, message: e.message })),
  };
}

// Persist edited Python as the runnable artifact. Sends ONLY source_code, so the
// graph is never regenerated/clobbered — code stays authoritative.
export async function saveStrategySource(id: string, source: string): Promise<DevStrategy> {
  if (!id || id === "builtin:" || id.startsWith(BUILTIN_PREFIX)) {
    throw new ApiError(400, "Built-in strategies can't be edited. Clone it first.");
  }
  const u = await api.put<ApiUserStrategy>(`/user-strategies/${id}`, { source_code: source });
  return userToDev(u);
}

export interface CodeGraphResult {
  ok: boolean;
  graph?: StrategyGraph;
  plan: string[];
  assumptions: string[];
  error?: string;
}

// AI: render the node graph that REPRESENTS the given Python source (reverse of
// graph->code). Best-effort VIEW — code remains the source of truth.
export async function planGraphFromCode(
  source: string,
  assetClass: AssetClass,
): Promise<CodeGraphResult> {
  const r = await api.post<{
    ok: boolean;
    graph?: { nodes: unknown[]; edges: unknown[] } | null;
    plan?: string[];
    assumptions?: string[];
    error?: string | null;
  }>("/user-strategies/plan-graph-from-code", {
    source_code: source,
    asset_class: ASSET_TO_VENUE_CLASS[assetClass] ? assetClass : "crypto",
  });
  return {
    ok: r.ok,
    graph: r.ok && r.graph ? (r.graph as unknown as StrategyGraph) : undefined,
    plan: r.plan ?? [],
    assumptions: r.assumptions ?? [],
    error: r.error ?? undefined,
  };
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

export interface RecentBacktest {
  id: string;
  strategyName: string;
  symbols: string[];
  status: string;
  createdAt: string;
  barResolution?: string; // normalized timeframe this run executed on
  totalReturn?: number; // fraction
  sharpe?: number;
  profitFactor?: number;
  trades?: number;
}

// Most-recent backtests across all the user's strategies, for the overview page.
export async function getRecentBacktests(limit = 12): Promise<RecentBacktest[]> {
  const list = await api.get<ApiBacktestSummary[]>("/backtests", { limit });
  return list.map((b) => ({
    id: b.id,
    strategyName: b.strategy_name,
    symbols: b.symbols,
    status: b.status,
    createdAt: b.created_at,
    barResolution: b.bar_resolution ? normalizeBarResolution(b.bar_resolution) : undefined,
    totalReturn: b.total_return_pct == null ? undefined : b.total_return_pct / 100,
    sharpe: b.sharpe_ratio ?? undefined,
    profitFactor: b.profit_factor ?? undefined,
    trades: b.num_closed_trades ?? undefined,
  }));
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

// Owner-scoped delete (204); 404 for a missing/foreign run.
export async function deleteBacktest(id: string): Promise<void> {
  await api.del<void>(`/backtests/${id}`);
}

// Block until an async backtest job settles, then return its full run.
async function awaitBacktest(id: string, maxPolls: number): Promise<BacktestRun> {
  for (let i = 0; i < maxPolls; i++) {
    const d = await api.get<ApiBacktestDetail>(`/backtests/${id}`);
    if (d.status === "completed") {
      const full = await getBacktest(id);
      if (full) return full;
    }
    if (d.status === "failed") throw new ApiError(500, d.error_message || "Backtest failed");
    await sleep(2000);
  }
  throw new ApiError(504, "Backtest timed out while waiting for results.");
}

// A completed run is immutable, so "editing" one means re-running it: clone the
// stored config into a fresh /backtests job and wait for the new run.
export async function cloneBacktest(id: string): Promise<BacktestRun> {
  const src = await api.get<ApiBacktestDetail>(`/backtests/${id}`);
  const { id: newId } = await api.post<{ id: string; status: string }>("/backtests", {
    strategy_name: src.strategy_name,
    params: src.params_json ?? {},
    symbols: src.symbols,
    bar_resolution: normalizeBarResolution(src.bar_resolution),
    starting_cash: num(src.starting_cash) || 10000,
    fee_rate_bps: src.fee_rate_bps ?? 10,
    slippage_bps: src.slippage_bps ?? 5,
    window_start: src.bars_start ?? undefined,
    window_end: src.bars_end ?? undefined,
  });
  return awaitBacktest(newId, Math.max(150, (src.symbols?.length ?? 1) * 3));
}

// Generate (and cache) the on-demand LLM narrative over a backtest's
// deterministic analysis. Returns ok=false (not throwing) when the LLM is
// unavailable — e.g. Anthropic credits exhausted — so the UI can show the
// reason while the structured findings stay visible.
export interface NarrativeResult {
  ok: boolean;
  narrative?: string | null;
  error?: string | null;
}
export function generateBacktestNarrative(id: string): Promise<NarrativeResult> {
  return api.post<NarrativeResult>(`/backtests/${id}/narrative`);
}

// AI parameter-tweak advisor: given a backtest's analysis + the strategy's
// graph, ask Claude which specific node parameters to change. Returns editable
// {node, field, current, suggested} tweaks the user can adjust and re-backtest.
// ok=false (not throwing) when the LLM is unavailable or there's no graph to tune.
export function suggestBacktestTweaks(
  id: string,
  graph: StrategyGraph,
): Promise<SuggestTweaksResult> {
  return api.post<SuggestTweaksResult>(`/backtests/${id}/suggest-tweaks`, {
    graph_json: graph,
  });
}

// Params the run modal collects. `symbols` carries the user's explicit asset
// choice (one, several, or a whole universe); when absent we fall back to
// resolving from the graph / asset class.
export type RunBacktestParams = BacktestRun["params"] & {
  symbols?: string[];
  barResolution?: string;
  // Optional inclusive date window (YYYY-MM-DD or ISO). Both set => bounded run
  // (e.g. a held-out out-of-sample segment); omitted => full history.
  windowStart?: string;
  windowEnd?: string;
};

// The bar resolutions the backend accepts (exact, lowercase). A graph node or a
// stale pref can carry variants like "1D"/"1H"/"1day"; POST /backtests validates
// strictly, so normalize here to avoid a 422 on an otherwise-valid run.
const BAR_RESOLUTIONS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
const BAR_ALIASES: Record<string, string> = {
  "1min": "1m", "5min": "5m", "15min": "15m",
  "60m": "1h", "1hr": "1h", "1hour": "1h",
  "4hr": "4h", "4hour": "4h",
  "1day": "1d", daily: "1d", "1w": "1d", "1wk": "1d",
};
export function normalizeBarResolution(tf?: string): string {
  const t = (tf ?? "").trim().toLowerCase();
  if ((BAR_RESOLUTIONS as readonly string[]).includes(t)) return t;
  return BAR_ALIASES[t] ?? "1h";
}

// The timeframe the graph declares on its `price` node — the source of truth for
// what a strategy runs on. Empty string when the graph doesn't say (built-in or
// code-only strategies), so callers can treat "unknown" as "not stale".
export function graphTimeframe(graph?: StrategyGraph | null): string {
  const tf = graph?.nodes?.find((n) => n.type === "price")?.data?.timeframe;
  return typeof tf === "string" && tf ? normalizeBarResolution(tf) : "";
}

export async function runBacktest(
  strategyId: string,
  params: RunBacktestParams,
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

  // Honor the explicit selection from the builder; otherwise infer.
  const symbols =
    params.symbols && params.symbols.length
      ? params.symbols
      : await resolveSymbols(graph, assetClass);
  if (symbols.length === 0) {
    throw new ApiError(
      422,
      "No tradable instruments available. Connect market data for this asset class, or pick a symbol.",
    );
  }

  // Resolve the bar resolution: an explicit override wins; otherwise use the
  // timeframe the strategy's `price` node declares (so a "1m" strategy actually
  // backtests on 1-minute bars and "hold 1 bar" means one minute, not one hour);
  // fall back to 1h only when the graph doesn't say. Normalize to the canonical
  // lowercase set the backend accepts — a graph or pref may carry "1D"/"1H".
  const priceTf = graph.nodes?.find((n) => n.type === "price")?.data?.timeframe;
  const barResolution = normalizeBarResolution(
    (params.barResolution as string | undefined) ||
      (typeof priceTf === "string" ? priceTf : ""),
  );

  // A bounded window (e.g. held-out OOS) sends both ends; absent => full
  // history. Dates are sent as ISO so the backend parses them as UTC instants.
  const toIso = (d?: string): string | undefined => {
    if (!d) return undefined;
    const t = new Date(d);
    return Number.isNaN(+t) ? undefined : t.toISOString();
  };
  const { id } = await api.post<{ id: string; status: string }>("/backtests", {
    strategy_name: name,
    params: {},
    symbols,
    bar_resolution: barResolution,
    starting_cash: params.capital > 0 ? params.capital : 10000,
    fee_rate_bps: Math.round(params.commissionBps) || 10,
    slippage_bps: Math.round(params.slippageBps) || 5,
    window_start: toIso(params.windowStart),
    window_end: toIso(params.windowEnd),
  });

  // Poll the async job to completion. Universe-scale runs (many symbols) take
  // longer, so scale the budget with the symbol count (~2s * N, min 5 min).
  const maxPolls = Math.max(150, symbols.length * 3);
  const full = await awaitBacktest(id, maxPolls);
  // awaitBacktest()/getBacktest() can't know the owning strategy (a backtest
  // detail only carries strategy_name) so it stamps the backtest id as
  // strategyId. We DO know it here — overwrite with the real one so callers can
  // navigate to /studio/backtests/$strategyId and the detail page resolves the
  // strategy instead of sitting on "Loading…" forever.
  return { ...full, strategyId };
}

// Active instruments for an asset class, as symbol options for the builder.
// `symbol` is the canonical id the backtest API expects (e.g. BTC-USDT@BINANCEUS).
// `bars` is the amount of historical data the instrument actually has — most
// instruments have little/none, and backtesting one of those yields zero trades,
// so the UI surfaces this and prefers symbols with history.
export interface InstrumentOption {
  symbol: string;
  assetClass: AssetClass;
  venue: string;
  bars: number;
  first?: string | null;
  last?: string | null;
}

interface ApiCoverage {
  canonical_symbol: string;
  bars: number;
  first?: string | null;
  last?: string | null;
}

export async function getInstrumentsForAsset(
  assetClass: AssetClass,
): Promise<InstrumentOption[]> {
  const wantClass = ASSET_TO_VENUE_CLASS[assetClass];
  const [all, coverage] = await Promise.all([
    api.get<ApiInstrument[]>("/instruments", { active: true }),
    // Coverage is best-effort — if it fails, every symbol just shows 0 bars.
    api.get<ApiCoverage[]>("/instruments/coverage").catch(() => [] as ApiCoverage[]),
  ]);
  const cov = new Map(coverage.map((c) => [c.canonical_symbol, c]));
  return all
    .filter((i) => i.asset_class === wantClass)
    .map((i) => {
      const c = cov.get(i.canonical_symbol);
      return {
        symbol: i.canonical_symbol,
        assetClass,
        venue: i.venue,
        bars: c?.bars ?? 0,
        first: c?.first ?? null,
        last: c?.last ?? null,
      };
    })
    // Symbols with real history first (most bars), then alphabetical — so the
    // default pick and the top of the list are always tradeable.
    .sort((a, b) => b.bars - a.bars || a.symbol.localeCompare(b.symbol));
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

// Broker services that move REAL money.
const REAL_MONEY_SERVICES = new Set(["binanceus", "alpaca_live"]);

// Which broker venue trades each asset class.
//   crypto          → Binance.US (real money — no paper sandbox exists)
//   stocks/options  → Alpaca paper (simulated funds)
function serviceForAsset(assetClass: AssetClass): string {
  return assetClass === "crypto" ? "binanceus" : "alpaca";
}

// Conservative live-trading guardrails for a shared real-money account. The
// backend requires both for any live (Binance.US) session.
const LIVE_MAX_ORDER_NOTIONAL = 500;
const LIVE_MAX_DAILY_LOSS = 250;

// Start a trading session for a strategy via /paper-sessions. Routes by asset
// class to the right venue using the user's OWN broker key — every user trades
// on their own broker account. (A shared platform key is used only if the
// server has ALLOW_PLATFORM_CREDENTIALS enabled for a demo deployment.)
//
// The venue determines the mode: Alpaca → paper (safe), Binance.US → live (real
// money). `opts.mode: "live"` is the caller's acknowledgement that a real-money
// venue is OK; without it, a real-money deploy is refused so a "paper" forward
// test never silently trades real funds.
export async function deployStrategyLive(
  strategyId: string,
  opts: { mode?: "paper" | "live" } = {},
): Promise<{ ok: boolean; sessionId?: string; mode: "paper" | "live" }> {
  const wantLive = opts.mode === "live";
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

  const wantService = serviceForAsset(assetClass);

  // Use the user's OWN broker key. The shared platform key is offered only when
  // the server enables it (demo mode); listPlatformCredentials returns [] by
  // default, so in the normal secure posture this resolves to a personal key.
  const [personal, platform] = await Promise.all([
    listApiCredentials().catch(() => []),
    listPlatformCredentials().catch(() => []),
  ]);
  const credential =
    personal.find((c) => c.service === wantService) ??
    platform.find((c) => c.service === wantService);

  if (!credential) {
    if (wantService === "alpaca") {
      throw new ApiError(
        400,
        "Stocks/options need your own Alpaca key. Connect one in Settings → Broker API keys to run a paper forward test.",
      );
    }
    throw new ApiError(
      400,
      "Crypto needs your own Binance.US key. Connect one in Settings → Broker API keys before deploying.",
    );
  }

  const isLive = REAL_MONEY_SERVICES.has(credential.service);
  if (isLive && !wantLive) {
    throw new ApiError(
      400,
      `This ${assetClass} strategy trades REAL money on ${credential.service === "binanceus" ? "Binance.US" : "the live broker"}. Use "Deploy Live" to confirm — it won't run as a paper forward test.`,
    );
  }

  const symbols = await resolveSymbols(graph, assetClass);
  if (symbols.length === 0) {
    throw new ApiError(422, "No tradable instruments are available for this strategy.");
  }

  const { id } = await createSession({
    strategy_name: name,
    symbols,
    asset_class: ASSET_TO_VENUE_CLASS[assetClass],
    bar_resolution: "1m",
    api_credential_id: credential.id,
    // Live (real-money) sessions require both guardrails server-side.
    ...(isLive
      ? { max_order_notional: LIVE_MAX_ORDER_NOTIONAL, max_daily_loss: LIVE_MAX_DAILY_LOSS }
      : {}),
  });
  return { ok: true, sessionId: id, mode: isLive ? "live" : "paper" };
}

export async function submitStrategyToBayn(_id: string) {
  // Phase 4: marketplace submission.
  return { ok: true };
}

// Keep the PipelineStage type referenced so future stage mapping stays typed.
export type { PipelineStage };

// ── Certification ────────────────────────────────────────────────────────
// Door into the live referee engine for a backtest the user already ran. The
// server sources the backtest's equity WITH per-bar exposure, so the
// exposure-aware integrity path engages and a normal low-frequency strategy
// reaches a real verdict instead of a false UNVERIFIABLE.
export interface CertResult {
  verification_id: string | null;
  verdict: "DEPLOY" | "HOLD_CONDITIONAL" | "REJECT" | "UNVERIFIABLE";
  insecure: boolean;
  declared_trials: number | null;
  n_trials_used: number | null;
  self_declared: boolean;
  report_url: string | null;
}

export async function certifyBacktest(
  backtestId: string,
  declaredTrials: number,
): Promise<CertResult> {
  return api.post<CertResult>(`/backtests/${backtestId}/certify`, {
    declared_trials: declaredTrials,
  });
}

// The signed one-page HTML research note for an issued cert (authed fetch).
export async function getCertReportHtml(verificationId: string): Promise<string> {
  return api.get<string>(`/referee/cert/${verificationId}/report`);
}

// ── Skip forward testing ─────────────────────────────────────────────────
// Explicit, recorded opt-out: advance a VALIDATED (oos-passed) strategy toward
// deployable WITHOUT forward testing. The server records forward_test="skipped"
// (never "passed"); default path (forward testing) is unchanged.
export interface SkipForwardTestResult {
  ok: boolean;
  forward_test: string; // "skipped"
  state: Record<string, unknown>;
}
export async function skipForwardTest(strategyId: string): Promise<SkipForwardTestResult> {
  return api.post<SkipForwardTestResult>(`/copilot/strategies/${strategyId}/skip-forward-test`);
}
