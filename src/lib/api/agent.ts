// Mock agent API. Structured so the chat handler swaps for a real MCP/LLM call later.
import type { StrategyGraph, StrategyNode, StrategyEdge, AssetClass } from "@/lib/types";

export type AgentMode = "trader" | "studio";
export type MCPTarget = "agent" | "bayn" | "robinhood";

export type AgentPlatform =
  | "claude-code" | "claude-desktop" | "chatgpt" | "codex" | "codex-cli" | "cursor" | "other";

export interface AgentPlatformInfo {
  id: AgentPlatform;
  name: string;
  install: string;        // exact command/instruction
  docsHref?: string;
}

export const BAYN_MCP_URL = "https://agent.bayn.app/mcp";
export const ROBINHOOD_MCP_URL = "https://agent.robinhood.com/mcp/trading";

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
};

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
  if (/(call|put|iv rank|otm|premium)/.test(p)) {
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

  // ── Freeform fallback: keyword sweep ──
  const symbol = /btc/.test(p) ? "BTC-PERP" : /eth/.test(p) ? "ETH-PERP" : /qqq/.test(p) ? "QQQ" : /es\b/.test(p) ? "ES" : "SPY";
  const cls: AssetClass =
    symbol === "BTC-PERP" || symbol === "ETH-PERP" ? "crypto" :
    symbol === "ES" ? "futures" : "stocks";
  const tf = /1m|minute/.test(p) ? "1m" : /5m/.test(p) ? "5m" : /15m/.test(p) ? "15m" : /1d|daily/.test(p) ? "1d" : "1h";

  const price = n("price","data",`Price · ${symbol} ${tf}`, { symbol, timeframe: tf }, { x: 40,  y: 80  });
  let last = price.id;
  const nodes: StrategyNode[] = [price]; const edges: StrategyEdge[] = [];
  const assumptions: string[] = [`Symbol = ${symbol}, timeframe = ${tf} (inferred).`];

  if (/rsi/.test(p))   { const x = n("rsi","indicator","RSI(14)", { period: 14 }, { x: 280, y: 80 }); nodes.push(x); edges.push(e(price.id,x.id)); last = x.id; }
  if (/ema/.test(p))   { const x = n("ema","indicator","EMA(20)", { period: 20 }, { x: 280, y: 160 }); nodes.push(x); edges.push(e(price.id,x.id)); last = x.id; }
  if (/macd/.test(p))  { const x = n("macd","indicator","MACD", { fast:12, slow:26, signal:9 }, { x: 280, y: 240 }); nodes.push(x); edges.push(e(price.id,x.id)); last = x.id; }
  if (/bollinger|bb/.test(p)) { const x = n("bb","indicator","BBands(20,2)", { period:20, stdDev:2 }, { x: 280, y: 320 }); nodes.push(x); edges.push(e(price.id,x.id)); last = x.id; }

  const cmp = n("comparator","logic","Condition", { op: /short|sell/.test(p) ? ">" : "<", value: 30 }, { x: 540, y: 120 });
  nodes.push(cmp); edges.push(e(last, cmp.id));

  const stopPct = /tight/.test(p) ? 1 : 2;
  const stop = n("stopLoss","risk", `Stop −${stopPct}%`, { type: "percent", value: stopPct }, { x: 800, y: 60 });
  const tp   = n("takeProfit","risk", "Target 2R", { type: "r_multiple", value: 2 }, { x: 800, y: 160 });
  nodes.push(stop, tp);

  const direction = /short|sell/.test(p) ? "SHORT" : "LONG";
  const entry = n("entry","signal", `Entry ${direction}`, { direction }, { x: 1060, y: 120 });
  nodes.push(entry);
  edges.push(e(cmp.id, entry.id), e(stop.id, entry.id), e(tp.id, entry.id));

  return {
    graph: { nodes, edges },
    assetClass: cls,
    name: `${symbol} ${direction === "SHORT" ? "Short" : "Long"} Setup`,
    plan: [
      `Pulling ${symbol} ${tf} price.`,
      "Wiring a condition and risk envelope.",
      `Emitting an ${direction} entry signal.`,
    ],
    assumptions,
  };
}

/* ──────────────────────────────────────────────────────────────
   Trader-mode AI: canned, grounded "analysis" responses
   ────────────────────────────────────────────────────────────── */

export interface ChatMsg { id: string; role: "user" | "assistant"; content: string; meta?: { kind?: "handoff" | "switch-mode" | "graph"; graph?: BuildResult } }

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

> To act on this, your connected agent can submit the trim through **Robinhood Agentic** with your confirmation.`,
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

> To trim or trail, your connected agent can route the order via Robinhood Agentic with your confirmation.`,
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

export async function chatStudioAI(prompt: string): Promise<ChatMsg> {
  await new Promise((r) => setTimeout(r, 500 + Math.random() * 400));
  const p = prompt.toLowerCase();

  if (/my (trades|portfolio|win rate|p&l|pnl)|analy[sz]e my/.test(p)) {
    return {
      id: uid("m"), role: "assistant",
      content: "Trade analysis is in **Trader mode**. Want me to build a strategy instead?",
      meta: { kind: "switch-mode" },
    };
  }

  const built = buildGraphFromPrompt(prompt);
  const planText = built.plan.map((l) => `- ${l}`).join("\n");
  const assumeText = built.assumptions.length ? `\n\n**Assumptions:** ${built.assumptions.join(" ")}` : "";
  return {
    id: uid("m"), role: "assistant",
    content: `Building **${built.name}**.\n\n${planText}${assumeText}\n\nGraph placed on the canvas — edit any node, then **Run Backtest** when you're ready.`,
    meta: { kind: "graph", graph: built },
  };
}

/* ──────────────────────────────────────────────────────────────
   Connection state (localStorage)
   ────────────────────────────────────────────────────────────── */

const LS_KEY = "bayn.mcp.connections";

export interface ConnectionState {
  platform: AgentPlatform | null;
  agent: boolean;
  bayn: boolean;
  robinhood: boolean;
  allowSignalRead: boolean;
}
const DEFAULT: ConnectionState = { platform: null, agent: false, bayn: false, robinhood: false, allowSignalRead: true };

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
