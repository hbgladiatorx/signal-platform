// Studio build assistant. The studio "build" chat calls the FastAPI backend's
// AI graph planner (POST /user-strategies/plan-graph), which uses Claude to turn
// a plain-English idea into a real node graph. The keyword heuristic below
// (buildGraphFromPrompt) is kept only as an OFFLINE FALLBACK for when the AI is
// unreachable or out of credits — it is no longer the primary path.
import type { StrategyGraph, StrategyNode, StrategyEdge, AssetClass } from "@/lib/types";
import { api } from "@/lib/api/client";

// Response shape of POST /user-strategies/plan-graph (see services/api/routers/
// user_strategies.py::PlanGraphResponse). ok=false ⇒ fall back to the heuristic.
interface PlanGraphResponse {
  ok: boolean;
  name?: string | null;
  assetClass?: AssetClass | null;
  plan?: string[];
  assumptions?: string[];
  questions?: BuilderQuestion[];
  graph?: StrategyGraph | null;
  error?: string | null;
}

export type AgentMode = "trader" | "studio";
export type MCPTarget = "agent" | "bayn" | "broker";

export type AgentPlatform =
  | "claude-code" | "claude-desktop" | "chatgpt" | "codex" | "codex-cli" | "cursor" | "other";

export interface AgentPlatformInfo {
  id: AgentPlatform;
  name: string;
  install: string;        // exact command/instruction
  docsHref?: string;
}

export const BAYN_MCP_URL = "https://agent.bayn.app/mcp";
export const BROKER_MCP_URL = "https://agent.broker.app/mcp/trading";

export const PLATFORMS: AgentPlatformInfo[] = [
  { id: "claude-code",    name: "Claude Code",    install: `claude mcp add bayn --transport http ${BAYN_MCP_URL}` },
  { id: "claude-desktop", name: "Claude Desktop", install: `Settings → Connectors → Add custom connector → ${BAYN_MCP_URL}` },
  { id: "chatgpt",        name: "ChatGPT",        install: `Settings → Connectors → Add MCP server → ${BAYN_MCP_URL}` },
  { id: "codex",          name: "Codex",          install: `Add MCP server → ${BAYN_MCP_URL}` },
  { id: "codex-cli",      name: "Codex CLI",      install: `codex mcp add bayn --url ${BAYN_MCP_URL}` },
  { id: "cursor",         name: "Cursor",         install: `Settings → MCP → New server → ${BAYN_MCP_URL}` },
  { id: "other",          name: "Other",          install: `Add an HTTP MCP server pointing at ${BAYN_MCP_URL}` },
];

/* ──────────────────────────────────────────────────────────────
   Natural-language → node graph engine
   ────────────────────────────────────────────────────────────── */

let nid = 0;
const uid = (p: string) => `${p}-${++nid}-${Math.random().toString(36).slice(2, 6)}`;

function n(
  type: string,
  category: StrategyNode["category"],
  label: string,
  data: Record<string, unknown>,
  position: { x: number; y: number },
): StrategyNode {
  return { id: uid(type), type, category, label, position, data };
}
function e(source: string, target: string): StrategyEdge {
  return { id: uid("e"), source, target };
}

type BuildResult = {
  graph: StrategyGraph;
  assetClass: AssetClass;
  name: string;
  plan: string[];          // streamed plain-english plan
  assumptions: string[];
  // Follow-up questions the builder asks to refine the graph. Each option is a
  // plain-english instruction that routes back through the tweak engine, so
  // answering refines the relevant node instead of rebuilding.
  questions?: BuilderQuestion[];
};

export interface BuilderQuestion {
  q: string;
  options: string[];
}

/** Hardcoded polished graphs for the example chips, plus keyword-based freeform. */
export function buildGraphFromPrompt(prompt: string): BuildResult {
  nid = 0;
  const p = prompt.toLowerCase();

  // ── 1) RSI mean-reversion on SPY (chip 1) ──
  if (/spy/.test(p) && /rsi/.test(p)) {
    const price   = n("price", "data", "Price · SPY 1h", { symbol: "SPY", timeframe: "1h" }, { x: 40,  y: 80  });
    const rsi     = n("rsi",   "indicator", "RSI(14)",   { period: 14 },                     { x: 280, y: 80  });
    const oversold= n("comparator","logic", "RSI < 30",  { op: "<", value: 30 },             { x: 540, y: 40  });
    const exit    = n("comparator","logic", "RSI > 50",  { op: ">", value: 50 },             { x: 540, y: 140 });
    const stop    = n("stopLoss","risk",    "Stop −1.5%",{ type: "percent", value: 1.5 },    { x: 800, y: 40  });
    const size    = n("positionSize","risk","Risk 1%",   { type: "percent_account", value: 1 }, { x: 800, y: 120 });
    const entry   = n("entry", "signal",    "Entry LONG",{ direction: "LONG" },              { x: 1060,y: 60  });
    const exitS   = n("exit",  "signal",    "Exit",      {},                                 { x: 1060,y: 160 });
    return {
      graph: {
        nodes: [price, rsi, oversold, exit, stop, size, entry, exitS],
        edges: [
          e(price.id, rsi.id),
          e(rsi.id, oversold.id), e(rsi.id, exit.id),
          e(oversold.id, entry.id), e(stop.id, entry.id), e(size.id, entry.id),
          e(exit.id, exitS.id),
        ],
      },
      assetClass: "stocks",
      name: "SPY RSI Mean-Reversion",
      plan: [
        "Reading SPY 1h price.",
        "Computing RSI(14).",
        "Entering LONG when RSI < 30 with 1% account risk and a 1.5% stop.",
        "Exiting when RSI crosses back above 50.",
      ],
      assumptions: ["Timeframe = 1h (good fit for RSI mean-reversion on SPY)."],
    };
  }

  // ── 2) BTC mean-reversion 2 ATR below 20 EMA (chip 2) ──
  if (/btc/.test(p) && /(ema|atr)/.test(p)) {
    const price = n("price","data","Price · BTC 1h",      { symbol: "BTC-PERP", timeframe: "1h" }, { x: 40,  y: 80  });
    const ema   = n("ema","indicator","EMA(20)",          { period: 20 },                          { x: 280, y: 40  });
    const atr   = n("atr","indicator","ATR(14)",          { period: 14 },                          { x: 280, y: 140 });
    const cond  = n("formula","indicator","close < EMA − 2·ATR", { expr: "close < ema20 - 2*atr14" }, { x: 540, y: 90  });
    const stop  = n("stopLoss","risk","Stop 3·ATR",       { type: "atr_multiple", value: 3 },      { x: 800, y: 40  });
    const tp    = n("takeProfit","risk","Target = EMA20", { type: "to_level", value: "ema20" },    { x: 800, y: 140 });
    const entry = n("entry","signal","Entry LONG",        { direction: "LONG" },                   { x: 1060,y: 90  });
    return {
      graph: {
        nodes: [price, ema, atr, cond, stop, tp, entry],
        edges: [e(price.id,ema.id), e(price.id,atr.id), e(ema.id,cond.id), e(atr.id,cond.id), e(cond.id,entry.id), e(stop.id,entry.id), e(tp.id,entry.id)],
      },
      assetClass: "crypto",
      name: "BTC EMA Mean-Reversion",
      plan: [
        "Pulling BTC-PERP 1h price.",
        "Computing EMA(20) and ATR(14).",
        "Long when price is 2·ATR below the EMA.",
        "Stop = 3·ATR, target = the EMA itself.",
      ],
      assumptions: ["BTC-PERP on 1h. Linear target back to mean."],
    };
  }

  // ── 3) Opening Range Breakout ES futures (chip 3) ──
  if (/(opening range|orb|breakout)/.test(p) && (/es|futures/.test(p) || /es\b/.test(p))) {
    const price = n("price","data","Price · ES 5m",      { symbol: "ES", timeframe: "5m" },        { x: 40,  y: 80  });
    const win   = n("timeWindow","logic","09:30–09:45",  { start: "09:30", end: "09:45" },         { x: 280, y: 40  });
    const orb   = n("formula","indicator","Range High",  { expr: "high_of(window)" },              { x: 280, y: 140 });
    const cmp   = n("comparator","logic","close > range high", { op: ">", value: "rangeHigh" },    { x: 540, y: 90  });
    const trail = n("stopLoss","risk","Trail 1%",        { type: "trailing_percent", value: 1 },   { x: 800, y: 40  });
    const size  = n("positionSize","risk","2 contracts", { type: "contracts", value: 2 },          { x: 800, y: 140 });
    const entry = n("entry","signal","Entry LONG",       { direction: "LONG" },                    { x: 1060,y: 90  });
    return {
      graph: {
        nodes: [price, win, orb, cmp, trail, size, entry],
        edges: [e(price.id,orb.id), e(win.id,orb.id), e(orb.id,cmp.id), e(price.id,cmp.id), e(cmp.id,entry.id), e(trail.id,entry.id), e(size.id,entry.id)],
      },
      assetClass: "futures",
      name: "ES Opening Range Breakout",
      plan: [
        "Pulling ES 5m price.",
        "Defining opening range = first 15 minutes (09:30–09:45 ET).",
        "Long on break above range high.",
        "Riding with a 1% trailing stop.",
      ],
      assumptions: ["First-15-min opening range. 2-contract base size."],
    };
  }

  // ── 4) Sell far-OTM SPY weekly calls when IV rank > 50 (chip 4) ──
  // Premium-SELLING only. Requires explicit selling intent — otherwise a prompt
  // like "buy apple calls at 30 RSI" (a directional long) wrongly matched here
  // and got rewritten into this canned SPY credit strategy.
  const isPremiumSell =
    /\b(iv ?rank|premium|condor|credit spread|theta|covered call|cash[- ]secured)\b/.test(p) ||
    (/\b(sell|write|short)\b/.test(p) && /\b(calls?|puts?|options?)\b/.test(p) && !/\bbuy\b/.test(p));
  if (isPremiumSell) {
    const chain = n("optionsChain","data","SPY weekly calls", { symbol: "SPY", side: "call", expiry: "weekly" }, { x: 40,  y: 80  });
    const iv    = n("formula","indicator","IV Rank",          { expr: "iv_rank(SPY,252)" },                       { x: 280, y: 40  });
    const delta = n("formula","indicator","|Δ| < 0.15",       { expr: "abs(delta) < 0.15" },                      { x: 280, y: 140 });
    const cmp   = n("comparator","logic","IV Rank > 50",      { op: ">", value: 50 },                             { x: 540, y: 40  });
    const filt  = n("and","logic","AND",                      {},                                                 { x: 540, y: 140 });
    const stop  = n("stopLoss","risk","Stop = 2× credit",     { type: "credit_multiple", value: 2 },              { x: 800, y: 40  });
    const tp    = n("takeProfit","risk","Take 50% of credit", { type: "credit_pct", value: 50 },                  { x: 800, y: 140 });
    const entry = n("entry","signal","Sell to Open",          { direction: "SHORT" },                             { x: 1060,y: 90  });
    return {
      graph: {
        nodes: [chain, iv, delta, cmp, filt, stop, tp, entry],
        edges: [e(chain.id,iv.id), e(chain.id,delta.id), e(iv.id,cmp.id), e(cmp.id,filt.id), e(delta.id,filt.id), e(filt.id,entry.id), e(stop.id,entry.id), e(tp.id,entry.id)],
      },
      assetClass: "options",
      name: "SPY Weekly Call Premium-Selling",
      plan: [
        "Pulling SPY weekly call chain, |Δ| < 0.15 (far OTM).",
        "Computing IV Rank vs the last 252 days.",
        "Selling to open when IV Rank > 50.",
        "Taking profit at 50% of credit, stopping at 2× credit.",
      ],
      assumptions: ["Weekly expiry, |Δ| < 0.15 ≈ far OTM."],
    };
  }

  // ── Freeform: real parse of the prompt into a strategy spec ──
  return parseFreeform(prompt);
}

/* ──────────────────────────────────────────────────────────────
   Freeform parser — turns plain English into a strategy spec, then
   a node graph. Handles symbol (incl. company names), instrument
   (shares / calls / puts and buy-vs-sell-to-open), entry & exit
   conditions with their own thresholds, indicators, timeframe, and
   a risk envelope. Anything it has to assume becomes a follow-up
   question so the user can refine the nodes.
   ────────────────────────────────────────────────────────────── */

// Company / index names → tradable tickers. Lower-cased keys.
const NAME_TO_TICKER: Record<string, string> = {
  apple: "AAPL", tesla: "TSLA", microsoft: "MSFT", amazon: "AMZN",
  google: "GOOGL", alphabet: "GOOGL", nvidia: "NVDA", meta: "META",
  facebook: "META", netflix: "NFLX", amd: "AMD", intel: "INTC",
  coinbase: "COIN", palantir: "PLTR", "s&p": "SPY", sp500: "SPY",
  "s&p 500": "SPY", nasdaq: "QQQ", "dow": "DIA", "russell": "IWM",
};
const NAME_TO_CRYPTO: Record<string, string> = {
  bitcoin: "BTC-PERP", btc: "BTC-PERP", ethereum: "ETH-PERP", eth: "ETH-PERP",
  solana: "SOL-PERP", sol: "SOL-PERP", dogecoin: "DOGE-PERP", doge: "DOGE-PERP",
};
// Uppercase tokens that are never tickers (indicators, words, sides).
const NOT_A_TICKER = new Set([
  "RSI", "EMA", "SMA", "MACD", "ATR", "BB", "VWAP", "IV", "AND", "OR", "NOT",
  "BUY", "SELL", "LONG", "SHORT", "CALL", "PUT", "CALLS", "PUTS", "THE", "AT",
  "TO", "OTM", "ITM", "TP", "SL", "OK", "USD",
]);

function resolveSymbol(prompt: string, p: string): { symbol: string | null; cls: AssetClass } {
  for (const [name, tic] of Object.entries(NAME_TO_CRYPTO)) {
    if (new RegExp(`\\b${name}\\b`).test(p)) return { symbol: tic, cls: "crypto" };
  }
  for (const [name, tic] of Object.entries(NAME_TO_TICKER)) {
    if (new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`).test(p)) {
      return { symbol: tic, cls: "stocks" };
    }
  }
  // Explicit uppercase ticker in the original (case-sensitive) prompt.
  const caps = prompt.match(/\b[A-Z]{1,5}(?:-[A-Z]+)?\b/g) ?? [];
  for (const c of caps) {
    if (!NOT_A_TICKER.has(c)) {
      const cls: AssetClass = c === "ES" || c === "NQ" ? "futures" : "stocks";
      return { symbol: c, cls };
    }
  }
  // Known futures words.
  if (/\bes\b|\bs&p futures\b/.test(p)) return { symbol: "ES", cls: "futures" };
  return { symbol: null, cls: "stocks" };
}

type Cond = { indicator: string; op: "<" | ">"; value: number; label: string };

// Pull an RSI/indicator threshold out of one clause, using the verb (buy =
// entry/oversold, sell = exit/overbought) to infer the operator when the
// prompt doesn't state "above/below" explicitly.
function parseCond(clause: string, side: "entry" | "exit"): Cond | null {
  const c = clause.toLowerCase();
  const rsi = c.match(/rsi[^0-9]{0,12}(\d{1,3})|(\d{1,3})[^0-9a-z]{0,6}rsi/);
  if (rsi) {
    const value = parseInt(rsi[1] ?? rsi[2], 10);
    let op: "<" | ">";
    if (/\b(below|under|less than|drops?|dips?|falls?|<)\b/.test(c)) op = "<";
    else if (/\b(above|over|greater than|exceeds?|crosses? above|reaches|>)\b/.test(c)) op = ">";
    else op = side === "entry" ? "<" : ">"; // buy oversold, sell overbought
    return { indicator: "rsi", op, value, label: `RSI ${op} ${value}` };
  }
  return null;
}

function parseFreeform(prompt: string): BuildResult {
  const p = prompt.toLowerCase();
  const { symbol: parsedSym, cls } = resolveSymbol(prompt, p);
  const symbolKnown = parsedSym != null;
  const symbol = parsedSym ?? "SPY";

  // Instrument: calls / puts / shares, and whether we open long or short.
  const isCall = /\bcalls?\b/.test(p);
  const isPut = /\bputs?\b/.test(p);
  const isOption = isCall || isPut;
  // "buy ... calls" → long calls (bullish). "sell/write calls" with no buy →
  // premium selling handled earlier; here a "sell" after a "buy" is an exit.
  const opensShort = isOption
    ? /\b(sell|write|short)\b/.test(p) && !/\bbuy\b/.test(p)
    : /\b(short|sell short|go short)\b/.test(p);
  const direction: "LONG" | "SHORT" = opensShort ? "SHORT" : "LONG";
  const assetClass: AssetClass = isOption ? "options" : cls;

  // Timeframe.
  const tfMatch = p.match(/\b(1m|5m|15m|30m|1h|2h|4h|1d)\b/) ||
    (/\bminute\b/.test(p) ? ["", "1m"] : /\bhourly\b/.test(p) ? ["", "1h"] : /\bdaily\b/.test(p) ? ["", "1d"] : null);
  const timeframeKnown = tfMatch != null;
  const timeframe = tfMatch ? tfMatch[1] : "1h";

  // Entry / exit conditions. Split on buy/sell verbs so each gets its own
  // threshold, then fall back to a whole-prompt scan.
  const entryClause = p.match(/\b(?:buy|long|enter|go long|open)\b[^.]*?(?=\band\b|\bthen\b|\bsell\b|\bexit\b|$)/)?.[0] ?? p;
  const exitClause = p.match(/\b(?:sell|exit|close|take profit|tp|target)\b[^.]*?$/)?.[0] ?? "";
  let entry = parseCond(entryClause, "entry") ?? parseCond(p, "entry");
  let exitCond = exitClause ? parseCond(exitClause, "exit") : null;

  // Other indicators mentioned (used as the data→signal chain when no RSI).
  const wantsEma = /\bema\b/.test(p);
  const wantsSma = /\bsma\b/.test(p);
  const wantsMacd = /\bmacd\b/.test(p);
  const wantsBB = /\b(bollinger|bbands?|bb)\b/.test(p);
  const hasIndicator = entry != null || wantsEma || wantsSma || wantsMacd || wantsBB;
  if (!entry && !hasIndicator) {
    // Nothing to key on — default to an RSI oversold entry so the graph runs.
    entry = { indicator: "rsi", op: "<", value: 30, label: "RSI < 30" };
  }

  // ── Build the graph ──
  nid = 0;
  const nodes: StrategyNode[] = [];
  const edges: StrategyEdge[] = [];
  const plan: string[] = [];
  const assumptions: string[] = [];

  // Underlying price feeds indicators (for options too — RSI is on the underlying).
  const price = n("price", "data", `Price · ${symbol} ${timeframe}`, { symbol, timeframe }, { x: 40, y: 120 });
  nodes.push(price);
  plan.push(`Reading ${symbol} ${timeframe} price.`);

  // Indicator node (RSI is the common case; otherwise the first one named).
  let indicatorId = price.id;
  if (entry?.indicator === "rsi" || /\brsi\b/.test(p)) {
    const rsi = n("rsi", "indicator", "RSI(14)", { period: 14 }, { x: 300, y: 120 });
    nodes.push(rsi); edges.push(e(price.id, rsi.id)); indicatorId = rsi.id;
    plan.push("Computing RSI(14).");
  } else if (wantsEma) {
    const ema = n("ema", "indicator", "EMA(20)", { period: 20 }, { x: 300, y: 120 });
    nodes.push(ema); edges.push(e(price.id, ema.id)); indicatorId = ema.id;
    plan.push("Computing EMA(20).");
  } else if (wantsSma) {
    const sma = n("sma", "indicator", "SMA(50)", { period: 50 }, { x: 300, y: 120 });
    nodes.push(sma); edges.push(e(price.id, sma.id)); indicatorId = sma.id;
    plan.push("Computing SMA(50).");
  } else if (wantsMacd) {
    const macd = n("macd", "indicator", "MACD(12,26,9)", { fast: 12, slow: 26, signal: 9 }, { x: 300, y: 120 });
    nodes.push(macd); edges.push(e(price.id, macd.id)); indicatorId = macd.id;
    plan.push("Computing MACD(12,26,9).");
  } else if (wantsBB) {
    const bb = n("bb", "indicator", "BBands(20,2)", { period: 20, stdDev: 2 }, { x: 300, y: 120 });
    nodes.push(bb); edges.push(e(price.id, bb.id)); indicatorId = bb.id;
    plan.push("Computing Bollinger Bands(20,2).");
  }

  // Entry condition.
  const entryC = entry ?? { indicator: "rsi", op: "<" as const, value: 30, label: "RSI < 30" };
  const entryCmp = n("comparator", "logic", entryC.label, { op: entryC.op, value: entryC.value }, { x: 560, y: 60 });
  nodes.push(entryCmp); edges.push(e(indicatorId, entryCmp.id));

  // Options chain node when trading calls/puts — declares the instrument.
  let chainId: string | null = null;
  if (isOption) {
    const side = isPut ? "put" : "call";
    const chain = n("optionsChain", "data", `${symbol} ${side}s`, { symbol, side, expiry: "weekly", deltaTarget: 0.5 }, { x: 300, y: 280 });
    nodes.push(chain); chainId = chain.id;
    assumptions.push(`Trading ${symbol} weekly ${side}s near 0.50 delta (ATM) — adjust the chain node for a different strike/expiry.`);
  }

  // Risk envelope (defaults; surfaced as questions to confirm).
  const stop = n("stopLoss", "risk", "Stop −2%", { type: "percent", value: 2 }, { x: 800, y: 40 });
  const size = n("positionSize", "risk", "Risk 1%", { type: "percent_account", value: 1 }, { x: 800, y: 140 });
  nodes.push(stop, size);

  // Entry signal.
  const buyWord = isOption ? (direction === "LONG" ? "Buy to Open" : "Sell to Open") : `Entry ${direction}`;
  const entrySig = n("entry", "signal", buyWord, { direction, instrument: isOption ? (isPut ? "put" : "call") : "equity" }, { x: 1060, y: 80 });
  nodes.push(entrySig);
  edges.push(e(entryCmp.id, entrySig.id), e(stop.id, entrySig.id), e(size.id, entrySig.id));
  if (chainId) edges.push(e(chainId, entrySig.id));
  plan.push(
    isOption
      ? `${direction === "LONG" ? "Buying" : "Selling"} ${symbol} ${isPut ? "puts" : "calls"} to open when ${entryC.label}.`
      : `Entering ${direction} when ${entryC.label}, risking 1% with a 2% stop.`,
  );

  // Exit condition (the "sell them at 70 RSI" half).
  if (exitCond) {
    const exitCmp = n("comparator", "logic", exitCond.label, { op: exitCond.op, value: exitCond.value }, { x: 560, y: 200 });
    const exitSig = n("exit", "signal", isOption ? "Sell to Close" : "Exit", {}, { x: 1060, y: 220 });
    nodes.push(exitCmp, exitSig);
    edges.push(e(indicatorId, exitCmp.id), e(exitCmp.id, exitSig.id));
    plan.push(`Exiting when ${exitCond.label}.`);
  } else {
    assumptions.push("No exit rule given — add one, or it'll exit on the stop/target.");
  }

  // Name.
  const kind = entryC.indicator === "rsi" ? "RSI" : wantsEma ? "EMA" : wantsMacd ? "MACD" : "Signal";
  const instr = isOption ? (isPut ? "Long Puts" : direction === "SHORT" ? "Short Calls" : "Long Calls") : direction === "SHORT" ? "Short" : "Long";
  const name = `${symbol} ${kind} ${instr}`;

  // Follow-up questions — each option routes back through the tweak engine.
  const questions: BuilderQuestion[] = [];
  if (!symbolKnown) {
    assumptions.push(`Couldn't find a ticker — defaulted to ${symbol}.`);
    questions.push({ q: "Which symbol should this trade?", options: ["Use AAPL", "Use SPY", "Use QQQ"] });
  }
  if (!timeframeKnown) {
    assumptions.push(`Timeframe = ${timeframe} (inferred).`);
    questions.push({ q: "What timeframe should it run on?", options: ["Use 15m timeframe", "Use 1h timeframe", "Use 1d timeframe"] });
  }
  questions.push({ q: "Confirm the protective stop (defaulted to 2%):", options: ["Set stop to 2%", "Set stop to 5%", "Set stop to 1.5x ATR"] });
  questions.push({ q: "How much to risk per trade (defaulted to 1%)?", options: ["Risk 1% per trade", "Risk 2% per trade"] });

  return { graph: { nodes, edges }, assetClass, name, plan, assumptions, questions: questions.slice(0, 3) };
}

/* ──────────────────────────────────────────────────────────────
   Tweak engine — patches an existing graph instead of rebuilding
   ────────────────────────────────────────────────────────────── */

export interface GraphContext {
  name: string;
  assetClass: AssetClass;
  nodes: StrategyNode[];
  edges: StrategyEdge[];
}

export interface TweakResult {
  graph: StrategyGraph;
  assetClass: AssetClass;
  name: string;
  changedNodeIds: string[];
  changes: string[]; // human-readable bullet list of what changed
}

const TWEAK_INTENT = /\b(change|set|update|adjust|tweak|raise|lower|increase|decrease|reduce|make|switch|swap|use|tighten|loosen|widen)\b/;

function nodeMatches(node: StrategyNode, kinds: string[], labelMatch?: RegExp): boolean {
  if (kinds.includes(node.type)) return true;
  if (labelMatch && labelMatch.test(node.label)) return true;
  return false;
}

/** Detect tweak prompts and patch an existing graph. Returns null if the prompt isn't a tweak. */
export function applyGraphTweak(prompt: string, ctx: GraphContext): TweakResult | null {
  if (!ctx.nodes.length) return null;
  const p = prompt.toLowerCase();
  if (!TWEAK_INTENT.test(p) && !/^\s*(stop|target|tp|sl|rsi|ema|sma|atr|size|risk|timeframe|symbol|long|short)\b/.test(p)) {
    return null;
  }
  // If the user names a totally different setup (a new strategy template), prefer rebuild.
  if (/\b(strategy|setup|build|create|design)\b/.test(p) && !/\b(this|current|existing|the strategy)\b/.test(p)) {
    return null;
  }

  const changed = new Set<string>();
  const changes: string[] = [];
  const nodes = ctx.nodes.map((n) => ({ ...n, data: { ...n.data } }));

  const findNodes = (kinds: string[], labelMatch?: RegExp) =>
    nodes.filter((n) => nodeMatches(n, kinds, labelMatch));

  // Stop loss tweaks
  if (/\bstop\b|\bsl\b/.test(p) || /tighten|loosen|widen/.test(p)) {
    const stops = findNodes(["stopLoss"], /stop/i);
    const atrMatch = p.match(/(\d+(?:\.\d+)?)\s*(?:x\s*)?atr/);
    const pctMatch = p.match(/stop[^%\n]{0,20}(\d+(?:\.\d+)?)\s*%/);
    const rMatch = p.match(/stop[^r\n]{0,20}(\d+(?:\.\d+)?)\s*r\b/);
    for (const s of stops) {
      if (atrMatch) {
        const v = parseFloat(atrMatch[1]);
        s.data.type = "atr_multiple"; s.data.value = v;
        s.label = `Stop ${v}·ATR`;
        changed.add(s.id);
        changes.push(`Stop → ${v}·ATR`);
      } else if (pctMatch) {
        const v = parseFloat(pctMatch[1]);
        s.data.type = "percent"; s.data.value = v;
        s.label = `Stop −${v}%`;
        changed.add(s.id);
        changes.push(`Stop → ${v}%`);
      } else if (rMatch) {
        const v = parseFloat(rMatch[1]);
        s.data.type = "r_multiple"; s.data.value = v;
        s.label = `Stop ${v}R`;
        changed.add(s.id);
        changes.push(`Stop → ${v}R`);
      }
    }
  }

  // Take profit / target tweaks
  if (/\btarget\b|\btake[\s-]?profit\b|\btp\b/.test(p)) {
    const tps = findNodes(["takeProfit"], /target|profit/i);
    const atrMatch = p.match(/(?:target|tp)[^a\n]{0,20}(\d+(?:\.\d+)?)\s*(?:x\s*)?atr/);
    const pctMatch = p.match(/(?:target|tp)[^%\n]{0,20}(\d+(?:\.\d+)?)\s*%/);
    const rMatch = p.match(/(?:target|tp)[^r\n]{0,20}(\d+(?:\.\d+)?)\s*r\b/);
    for (const t of tps) {
      if (atrMatch) {
        const v = parseFloat(atrMatch[1]);
        t.data.type = "atr_multiple"; t.data.value = v;
        t.label = `Target ${v}·ATR`;
        changed.add(t.id);
        changes.push(`Target → ${v}·ATR`);
      } else if (pctMatch) {
        const v = parseFloat(pctMatch[1]);
        t.data.type = "percent"; t.data.value = v;
        t.label = `Target +${v}%`;
        changed.add(t.id);
        changes.push(`Target → +${v}%`);
      } else if (rMatch) {
        const v = parseFloat(rMatch[1]);
        t.data.type = "r_multiple"; t.data.value = v;
        t.label = `Target ${v}R`;
        changed.add(t.id);
        changes.push(`Target → ${v}R`);
      }
    }
  }

  // Indicator period tweaks (RSI / EMA / SMA / ATR / BB)
  const periodSpecs: Array<{ re: RegExp; kinds: string[]; labelRe: RegExp; abbr: string }> = [
    { re: /rsi(?:\s*\(|\s*period|\s+to|\s+at|\s+)\s*(\d+)/, kinds: ["rsi"], labelRe: /rsi/i, abbr: "RSI" },
    { re: /ema(?:\s*\(|\s*period|\s+to|\s+at|\s+)\s*(\d+)/, kinds: ["ema"], labelRe: /ema/i, abbr: "EMA" },
    { re: /sma(?:\s*\(|\s*period|\s+to|\s+at|\s+)\s*(\d+)/, kinds: ["sma"], labelRe: /sma/i, abbr: "SMA" },
    { re: /atr(?:\s*\(|\s*period|\s+to|\s+at|\s+)\s*(\d+)/, kinds: ["atr"], labelRe: /atr/i, abbr: "ATR" },
  ];
  for (const spec of periodSpecs) {
    const m = p.match(spec.re);
    if (!m) continue;
    const v = parseInt(m[1], 10);
    const matches = findNodes(spec.kinds, spec.labelRe);
    for (const node of matches) {
      node.data.period = v;
      node.label = `${spec.abbr}(${v})`;
      changed.add(node.id);
      changes.push(`${spec.abbr} period → ${v}`);
    }
  }

  // Timeframe
  const tfMatch = p.match(/\b(1m|5m|15m|30m|1h|2h|4h|1d|daily|hourly|minute)\b/);
  if (tfMatch && /timeframe|interval|chart|tf|switch|use|change/.test(p)) {
    const tf = tfMatch[1] === "daily" ? "1d" : tfMatch[1] === "hourly" ? "1h" : tfMatch[1] === "minute" ? "1m" : tfMatch[1];
    for (const node of findNodes(["price"], /price/i)) {
      node.data.timeframe = tf;
      const sym = (node.data.symbol as string) ?? "";
      node.label = `Price · ${sym} ${tf}`;
      changed.add(node.id);
      changes.push(`Timeframe → ${tf}`);
    }
  }

  // Symbol switch. Match against the ORIGINAL-case prompt — tickers are
  // uppercase, and `p` is lowercased so [A-Z] would never hit.
  const symMatch = prompt.match(/\b(symbol|ticker)\s+(?:to\s+)?([A-Za-z]{2,6}(?:-[A-Za-z]+)?)\b/i)
    || prompt.match(/\b(?:use|switch to|change to|trade)\s+([A-Z]{2,6}(?:-[A-Z]+)?)\b/);
  if (symMatch) {
    const sym = (symMatch[2] ?? symMatch[1]).toUpperCase();
    for (const node of findNodes(["price"], /price/i)) {
      node.data.symbol = sym;
      const tf = (node.data.timeframe as string) ?? "1h";
      node.label = `Price · ${sym} ${tf}`;
      changed.add(node.id);
      changes.push(`Symbol → ${sym}`);
    }
  }

  // Position size / risk per trade
  const riskMatch = p.match(/(?:risk|size|position)[^%\n]{0,20}(\d+(?:\.\d+)?)\s*%/);
  if (riskMatch) {
    const v = parseFloat(riskMatch[1]);
    for (const node of findNodes(["positionSize"], /size|risk/i)) {
      node.data.type = "percent_account"; node.data.value = v;
      node.label = `Risk ${v}%`;
      changed.add(node.id);
      changes.push(`Risk per trade → ${v}%`);
    }
  }

  // Direction flip
  if (/\b(switch|flip|change)\b.*\b(short|long)\b/.test(p) || /^(go|make it|trade)\s+(long|short)/.test(p)) {
    const dir = /short/.test(p) ? "SHORT" : "LONG";
    for (const node of findNodes(["entry"], /entry/i)) {
      node.data.direction = dir;
      node.label = `Entry ${dir}`;
      changed.add(node.id);
      changes.push(`Direction → ${dir}`);
    }
  }

  if (!changed.size) return null;

  return {
    graph: { nodes, edges: ctx.edges },
    assetClass: ctx.assetClass,
    name: ctx.name,
    changedNodeIds: [...changed],
    changes,
  };
}

/* ──────────────────────────────────────────────────────────────
   Trader-mode AI: canned, grounded "analysis" responses
   ────────────────────────────────────────────────────────────── */

export interface ChatMsg {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta?: {
    kind?: "handoff" | "switch-mode" | "graph" | "tweak";
    graph?: BuildResult;
    tweak?: TweakResult;
    questions?: BuilderQuestion[];
  };
}

export async function chatTraderAI(prompt: string): Promise<ChatMsg> {
  await new Promise((r) => setTimeout(r, 600 + Math.random() * 500));
  const p = prompt.toLowerCase();

  if (/build|create|make.*strategy|node|graph|backtest a strategy/.test(p)) {
    return {
      id: uid("m"), role: "assistant",
      content: "Strategy building lives in **Studio mode**. Switch to Studio and I'll build it with you in the node editor.",
      meta: { kind: "switch-mode" },
    };
  }

  if (/risk|exposure/.test(p)) {
    return {
      id: uid("m"), role: "assistant",
      content:
`**Current risk exposure**

- Net delta is **+62%** long, concentrated in **futures (ES, NQ)** at 41% of capital.
- Your worst-case daily loss across open positions ≈ **$1,840** (7.4% of $25k account) — above your 5% guardrail.
- Crypto exposure (BTC-PERP long) adds correlated tech-beta on top of NQ.

**What I'd watch:** an ES gap-down would compound with BTC overnight risk. Trimming one ES contract drops worst-case to ~$1,180 (4.7%).

> To act on this, your connected agent can submit the trim through **Brokerage Agent** with your confirmation.`,
      meta: { kind: "handoff" },
    };
  }

  if (/underperform|backtest/.test(p)) {
    return {
      id: uid("m"), role: "assistant",
      content:
`**Subscribed strategies vs their backtests (last 30d):**

| Strategy | Backtest Sharpe | Live Sharpe | Δ |
|---|---|---|---|
| QQQ Momentum Pullback | 1.82 | **0.74** | −1.08 ⚠ |
| BTC Funding Reversion | 1.41 | 1.36 | flat |
| SPX 0DTE Iron Condor | 0.95 | 1.12 | +0.17 |

**QQQ Momentum Pullback** is the outlier — 4 of its last 6 signals hit stop, all on gap-down opens it never saw in-sample. Consider pausing follows until the dev runs a fresh OOS.`,
    };
  }

  if (/win rate|asset class/.test(p)) {
    return {
      id: uid("m"), role: "assistant",
      content:
`**Win rate by asset class (last 90d, 47 trades):**

- Stocks: **62%** (13/21), avg +0.9R
- Crypto: **48%** (10/21) — strong wins but choppy
- Futures: **40%** (2/5), avg −0.3R — small sample, but every loss was overnight

Your edge is concentrated in **stocks**. Futures look like a sample-size issue — re-check after 20+ more signals before drawing conclusions.`,
    };
  }

  if (/stop|last (three|3)/.test(p)) {
    return {
      id: uid("m"), role: "assistant",
      content:
`**Last 3 stopped signals:**

1. **AAPL long** — fired pre-CPI print, stop hit on the −1.4% spike at 08:31. The strategy doesn't include an econ-calendar filter.
2. **BTC-PERP long** — entered into a falling-VWAP regime; signal logic ignores VWAP slope.
3. **NQ short** — stop placed inside prior-day high cluster, fill slipped 3 ticks.

Common thread: **regime/context filters** are missing. The signals are valid in trend, weak in chop.`,
    };
  }

  if (/bull|bear case/.test(p)) {
    return {
      id: uid("m"), role: "assistant",
      content:
`**Open BTC-PERP long @ 62,400 — bull vs bear:**

**Bull**
- Funding has normalized after Friday's flush; spot bid persistent above 61.8k.
- ETF net flows turned positive 2 sessions running.

**Bear**
- Daily RSI(14) at 71 — same level that capped the last 3 rallies.
- Macro: DXY firming into FOMC; risk-off pocket likely Wed AM.

**Net:** asymmetric but late. A trail to 61.2k locks +1.0R and keeps optionality.

> To trim or trail, your connected agent can route the order via Brokerage Agent with your confirmation.`,
      meta: { kind: "handoff" },
    };
  }

  // generic
  return {
    id: uid("m"), role: "assistant",
    content:
`Looking at your account, **win rate is 54% over 47 trades** with an avg +0.42R. The clearest issue is **futures (overnight risk)** dragging the curve.

Ask me about: risk exposure, win rate by asset class, underperforming strategies, or why specific signals stopped out.`,
  };
}

/** Format a finished BuildResult into the assistant ChatMsg the canvas consumes. */
function graphMessage(built: BuildResult): ChatMsg {
  const planText = built.plan.map((l) => `- ${l}`).join("\n");
  const assumeText = built.assumptions.length ? `\n\n**Assumptions:** ${built.assumptions.join(" ")}` : "";
  const hasQs = built.questions && built.questions.length > 0;
  const tail = hasQs
    ? "\n\nGraph placed on the canvas. Answer a few questions below to refine it — or edit any node directly and **Run Backtest** when you're ready."
    : "\n\nGraph placed on the canvas — edit any node, then **Run Backtest** when you're ready.";
  return {
    id: uid("m"), role: "assistant",
    content: `Building **${built.name}**.\n\n${planText}${assumeText}${tail}`,
    meta: { kind: "graph", graph: built, questions: built.questions },
  };
}

export async function chatStudioAI(prompt: string, ctx?: GraphContext): Promise<ChatMsg> {
  const p = prompt.toLowerCase();

  if (/my (trades|portfolio|win rate|p&l|pnl)|analy[sz]e my/.test(p)) {
    return {
      id: uid("m"), role: "assistant",
      content: "Trade analysis is in **Trader mode**. Want me to build a strategy instead?",
      meta: { kind: "switch-mode" },
    };
  }

  // Fast offline path: if the user is clearly editing an existing graph and the
  // local tweak engine recognises the instruction, patch in-place instantly —
  // no round-trip, no LLM. Anything it doesn't recognise falls through to AI.
  if (ctx && ctx.nodes.length && TWEAK_INTENT.test(p)) {
    const tweak = applyGraphTweak(prompt, ctx);
    if (tweak) {
      const bullets = tweak.changes.map((c) => `- ${c}`).join("\n");
      return {
        id: uid("m"), role: "assistant",
        content: `Tweaking **${tweak.name}** — keeping the rest of the graph intact.\n\n${bullets}\n\nThe affected node${tweak.changedNodeIds.length === 1 ? " is" : "s are"} highlighted on the canvas.`,
        meta: { kind: "tweak", tweak },
      };
    }
  }

  // Primary path: AI builds the graph from the prompt. The backend reasons about
  // the actual intent (time-based, price-action, indicator, …) and places real
  // palette nodes — unlike the keyword heuristic, which mapped everything to RSI.
  try {
    const res = await api.post<PlanGraphResponse>("/user-strategies/plan-graph", {
      prompt,
      asset_class: ctx?.assetClass,
      graph_json: ctx && ctx.nodes.length ? { nodes: ctx.nodes, edges: ctx.edges } : undefined,
    });
    if (res.ok && res.graph && res.graph.nodes?.length) {
      const built: BuildResult = {
        graph: res.graph,
        assetClass: (res.assetClass as AssetClass) ?? "crypto",
        name: res.name ?? "Strategy",
        plan: res.plan ?? [],
        assumptions: res.assumptions ?? [],
        questions: res.questions ?? [],
      };
      return graphMessage(built);
    }
    // ok=false (out of credits, no key, no structured output) → offline fallback.
    if (res.error) console.warn("AI builder unavailable, using offline builder:", res.error);
  } catch (err) {
    console.warn("AI builder request failed, using offline builder:", err);
  }

  // Offline fallback: keyword heuristic so the builder still works if the AI is
  // unreachable. Lower fidelity — it can't reason about novel intents.
  return graphMessage(buildGraphFromPrompt(prompt));
}

/* ──────────────────────────────────────────────────────────────
   Connection state (localStorage)
   ────────────────────────────────────────────────────────────── */

const LS_KEY = "bayn.mcp.connections";

export interface ConnectionState {
  platform: AgentPlatform | null;
  agent: boolean;
  bayn: boolean;
  broker: boolean;
  allowSignalRead: boolean;
}
const DEFAULT: ConnectionState = { platform: null, agent: false, bayn: false, broker: false, allowSignalRead: true };

export function getConnections(): ConnectionState {
  if (typeof window === "undefined") return DEFAULT;
  try { return { ...DEFAULT, ...(JSON.parse(localStorage.getItem(LS_KEY) || "{}") as object) }; } catch { return DEFAULT; }
}
export function setConnections(c: ConnectionState) {
  if (typeof window === "undefined") return;
  localStorage.setItem(LS_KEY, JSON.stringify(c));
  window.dispatchEvent(new Event("bayn.mcp.changed"));
}

/* ──────────────────────────────────────────────────────────────
   Deployability
   ────────────────────────────────────────────────────────────── */

export type DeployStage = "draft" | "backtested" | "oos" | "forward" | "deployable" | "eligible";

export function deployStageMeta(s: DeployStage) {
  switch (s) {
    case "draft":      return { label: "Needs backtest",                icon: "❌", tone: "danger",   next: "Run a backtest to unlock out-of-sample." };
    case "backtested": return { label: "Backtested — needs OOS",        icon: "⚠️", tone: "warn",     next: "Run an out-of-sample test on a held-out window." };
    case "oos":        return { label: "OOS passed — needs forward",    icon: "⚠️", tone: "warn",     next: "Deploy to forward test for 7+ days of live signals." };
    case "forward":    return { label: "Forward testing",               icon: "🔄", tone: "info",     next: "Keep accumulating live signals to qualify." };
    case "deployable": return { label: "Deployable",                    icon: "✅", tone: "ok",       next: "Runs live for your personal signals." };
    case "eligible":   return { label: "Bayn-eligible",                 icon: "🏆", tone: "violet",   next: "30+ live days hit — submit to the Bayn catalog." };
  }
}
