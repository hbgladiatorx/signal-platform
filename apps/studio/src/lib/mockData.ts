import type {
  Strategy, Signal, MarketTile, EquityPoint, TakenSignal, AssetClass,
  DevStrategy, BacktestRun, PersonalSignal, StudioEarning,
} from "./types";

function mulberry32(seed: number) {
  return function () {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function walk(seed: number, n: number, start: number, vol: number, drift = 0) {
  const r = mulberry32(seed);
  const out: number[] = [start];
  for (let i = 1; i < n; i++) {
    const last = out[i - 1];
    const step = (r() - 0.5) * vol * last + drift * last;
    out.push(Math.max(0.01, last + step));
  }
  return out;
}

function isoDaysAgo(days: number, hourOffset = 0) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(d.getHours() - hourOffset);
  return d.toISOString();
}

/* ---------------- Market overview ---------------- */
export const marketTiles: MarketTile[] = [
  { symbol: "SPY", label: "S&P 500 ETF", assetClass: "stocks", price: 583.12, changePct: 0.42, spark: walk(1, 30, 580, 0.004, 0.0005) },
  { symbol: "QQQ", label: "Nasdaq 100", assetClass: "stocks", price: 498.77, changePct: 0.68, spark: walk(2, 30, 495, 0.006, 0.0008) },
  { symbol: "AAPL", label: "Apple", assetClass: "stocks", price: 228.4, changePct: 0.31, spark: walk(7, 30, 226, 0.005, 0.0003) },
  { symbol: "NVDA", label: "Nvidia", assetClass: "stocks", price: 138.2, changePct: 1.84, spark: walk(8, 30, 132, 0.012, 0.0014) },
  { symbol: "BTC", label: "Bitcoin", assetClass: "crypto", price: 71240, changePct: -1.12, spark: walk(3, 30, 72500, 0.012, -0.0004) },
  { symbol: "ETH", label: "Ethereum", assetClass: "crypto", price: 3812, changePct: 2.04, spark: walk(4, 30, 3700, 0.015, 0.0012) },
  { symbol: "ES", label: "S&P Futures", assetClass: "futures", price: 5821.5, changePct: 0.31, spark: walk(5, 30, 5810, 0.004, 0.0003) },
  { symbol: "CL", label: "WTI Crude", assetClass: "futures", price: 71.4, changePct: -0.84, spark: walk(9, 30, 72, 0.008, -0.0006) },
  { symbol: "VIX", label: "Volatility", assetClass: "index" as AssetClass, price: 13.84, changePct: -3.42, spark: walk(6, 30, 15, 0.03, -0.003) },
];

/* ---------------- Bayn catalog strategies (16 total — no dev attribution shown to traders) ---------------- */
type SDef = Omit<Strategy, "stats" | "lastSignalAt" | "createdAt" | "status" | "edgeVerified" | "stage"> & {
  seed: number; sharpe: number; winRate: number; maxDD: number; sample: number; live: number; subs: number; avgR: number;
};

const stratDefs: SDef[] = [
  // Stocks (4)
  { id: "s-ore-mega", name: "Opening Range Breakout — Mega Caps", description: "First 30-min range breakout on liquid large caps with volume confirmation.", longDescription: "Trades the breakout of the first 30-minute range on a curated basket of mega-cap equities.", entryRules: "After 10:00 ET, close above 9:30–10:00 range high on >1.4x average opening volume → long.", exitRules: "Stop = range low. Target = 2x range height. Time stop 15:45 ET.", assetClass: "stocks", devHandle: "", symbols: ["AAPL","MSFT","NVDA","AMZN","META"], seed: 11, sharpe: 1.42, winRate: 0.54, maxDD: 0.11, sample: 612, live: 184, subs: 1247, avgR: 0.38 },
  { id: "s-earn-drift", name: "Earnings Drift — Mid-Cap Tech", description: "Post-earnings drift on mid-cap tech beats with raised guidance.", longDescription: "Buys mid-cap tech ($2B–$20B) the morning after an earnings beat with raised guidance.", entryRules: "Beat EPS >5%, raised guide, gap +3% to +9% on >2x avg volume.", exitRules: "Stop = gap-fill. Target = +12%. Time stop = 10 trading days.", assetClass: "stocks", devHandle: "", symbols: ["mid-cap tech basket"], seed: 12, sharpe: 1.81, winRate: 0.61, maxDD: 0.14, sample: 287, live: 312, subs: 894, avgR: 0.71 },
  { id: "s-meanrev-spy", name: "Mean Reversion — SPY 2-Day", description: "Buys SPY oversold 2-day RSI extremes in established uptrends.", longDescription: "Classic mean reversion: SPY above 200-day SMA and 2-day RSI below 10.", entryRules: "SPY > 200 SMA AND RSI(2) < 10 → enter long next open.", exitRules: "Exit when RSI(2) > 70 OR after 5 trading days.", assetClass: "stocks", devHandle: "", symbols: ["SPY"], seed: 13, sharpe: 1.08, winRate: 0.67, maxDD: 0.08, sample: 451, live: 421, subs: 2103, avgR: 0.22 },
  { id: "s-gap-fill", name: "Gap Fill — Russell Small Caps", description: "Fades unfilled overnight gaps on liquid small caps without news.", longDescription: "Fades morning gaps > 1.5% with no associated news catalyst on Russell 2000 components.", entryRules: "Gap > 1.5% at open, no headlines, fade at 9:45 ET.", exitRules: "Target = prior close. Stop = 1× ATR(14) from entry.", assetClass: "stocks", devHandle: "", symbols: ["IWM basket"], seed: 14, sharpe: 0.96, winRate: 0.58, maxDD: 0.13, sample: 392, live: 156, subs: 612, avgR: 0.31 },

  // Crypto (4)
  { id: "s-btc-hourly-mr", name: "Mean Reversion — BTC Hourly", description: "Hourly BTC fades of 3-sigma deviations from the 50-period VWAP.", longDescription: "Fades extreme hourly deviations from VWAP on BTC perpetual. Skips NYSE open ±15 min.", entryRules: "Price > 3σ above 50-hour VWAP → short. < 3σ below → long.", exitRules: "Target = VWAP. Stop = 1.5x entry deviation.", assetClass: "crypto", devHandle: "", symbols: ["BTC-PERP"], seed: 21, sharpe: 1.64, winRate: 0.58, maxDD: 0.17, sample: 1284, live: 198, subs: 3412, avgR: 0.41 },
  { id: "s-eth-mom", name: "Momentum Continuation — ETH 4H", description: "Buys ETH 4-hour higher-high breakouts confirmed by funding flip.", longDescription: "Catches established ETH uptrends with a higher-high breakout aligned to positive funding.", entryRules: "4H higher high after 3 higher lows AND funding > 0.005%.", exitRules: "Trail stop at prior swing low. No fixed target.", assetClass: "crypto", devHandle: "", symbols: ["ETH-PERP"], seed: 22, sharpe: 1.21, winRate: 0.46, maxDD: 0.21, sample: 318, live: 256, subs: 1782, avgR: 0.84 },
  { id: "s-sol-vol", name: "Volatility Breakout — SOL Daily", description: "Daily volatility expansion on SOL with regime filter.", longDescription: "Trades daily volatility expansion when realized vol compresses then breaks out.", entryRules: "30D realized vol < 30D median × 0.7 AND close > prior 5-day high.", exitRules: "Chandelier stop, ATR(14) × 3. Time stop 21 days.", assetClass: "crypto", devHandle: "", symbols: ["SOL-USD"], seed: 23, sharpe: 0.94, winRate: 0.41, maxDD: 0.23, sample: 204, live: 147, subs: 612, avgR: 0.96 },
  { id: "s-btc-funding", name: "Funding Rate Skew — BTC Perp", description: "Fades persistent funding extremes on BTC perps across major exchanges.", longDescription: "Identifies sustained 3-period funding extremes and fades crowded positioning.", entryRules: "Funding > 99th percentile 3 prints in a row → short. Inverse for longs.", exitRules: "Exit when funding returns to neutral or 24 hours.", assetClass: "crypto", devHandle: "", symbols: ["BTC-PERP"], seed: 24, sharpe: 1.33, winRate: 0.62, maxDD: 0.15, sample: 472, live: 138, subs: 821, avgR: 0.36 },

  // Options (4)
  { id: "s-spy-otm-put", name: "Far-OTM Weekly Premium — SPY", description: "Sells 5-delta SPY weekly puts in low-VIX regimes.", longDescription: "Sells 5-delta SPY weekly puts when VIX is below its 60-day median and term structure is in contango.", entryRules: "VIX < 60D median AND VX1/VX2 < 1.0. Sell 5-delta weekly put spread.", exitRules: "Close at 50% max profit or 21 DTE. Stop at 2× credit.", assetClass: "options", devHandle: "", symbols: ["SPY"], seed: 31, sharpe: 1.36, winRate: 0.83, maxDD: 0.12, sample: 244, live: 392, subs: 1521, avgR: 0.18 },
  { id: "s-iwm-iron-condor", name: "IWM Iron Condor — 30 DTE", description: "Monthly 16-delta iron condors on IWM with rolling rules.", longDescription: "Sells 16-delta iron condors at 30–45 DTE with mechanical roll rules.", entryRules: "First trading day each month: open 16-delta iron condor, 30–45 DTE, wings 4 strikes wide.", exitRules: "Close at 50% max profit. Roll tested side at 21 DTE if challenged.", assetClass: "options", devHandle: "", symbols: ["IWM"], seed: 32, sharpe: 0.88, winRate: 0.72, maxDD: 0.19, sample: 198, live: 271, subs: 478, avgR: 0.21 },
  { id: "s-nvda-call-diag", name: "NVDA Call Diagonal — Earnings", description: "Diagonal calls into NVDA earnings exploiting front-week IV crush.", longDescription: "Long a 60 DTE call, short a 7 DTE call, opened a week before NVDA earnings.", entryRules: "7 days before earnings, when front-week IV / back-month IV > 1.35.", exitRules: "Close the day after earnings.", assetClass: "options", devHandle: "", symbols: ["NVDA"], seed: 33, sharpe: 1.92, winRate: 0.58, maxDD: 0.18, sample: 64, live: 102, subs: 311, avgR: 1.12 },
  { id: "s-qqq-skew", name: "QQQ Skew Reversal — 45 DTE", description: "Sells put skew on QQQ when VIX9D crosses below VIX.", longDescription: "Risk-reversal-style trade harvesting elevated downside skew during fear regimes.", entryRules: "VIX9D crosses below VIX AND skew percentile > 80 → sell 25Δ put, buy 25Δ call, 45 DTE.", exitRules: "Close at 30% of max gain or 14 DTE.", assetClass: "options", devHandle: "", symbols: ["QQQ"], seed: 34, sharpe: 1.18, winRate: 0.64, maxDD: 0.16, sample: 132, live: 211, subs: 542, avgR: 0.44 },

  // Futures (4)
  { id: "s-mes-orb", name: "MES Opening Range Reversal", description: "Fades the MES opening range when overnight gap is closed.", longDescription: "Fades the opening 15-minute range on MES when the overnight gap is closed in the first 10 minutes.", entryRules: "Overnight gap closes within first 10 min. Enter at break of opposite end of 15-min range.", exitRules: "Stop = range high (or low). Target = 1.5× range height.", assetClass: "futures", devHandle: "", symbols: ["MES"], seed: 41, sharpe: 1.27, winRate: 0.52, maxDD: 0.13, sample: 488, live: 167, subs: 921, avgR: 0.44 },
  { id: "s-mnq-trend", name: "MNQ Trend-Day Continuation", description: "Catches MNQ trend-day legs after a confirmed midday breakout.", longDescription: "Identifies trend days on MNQ and enters on the first pullback after a 12:00 ET breakout.", entryRules: "12:00 ET breakout of midday range, then first pullback to VWAP that holds.", exitRules: "Trail under each 15-min swing low. Hard stop at VWAP loss.", assetClass: "futures", devHandle: "", symbols: ["MNQ"], seed: 42, sharpe: 1.55, winRate: 0.49, maxDD: 0.15, sample: 372, live: 211, subs: 1334, avgR: 0.82 },
  { id: "s-mcl-overnight", name: "MCL Overnight Inventory Fade", description: "MCL overnight inventory fade based on RTH closing range.", longDescription: "Fades MCL overnight imbalances back to prior RTH close when overnight extends > 0.7 ATR.", entryRules: "Overnight high > prior RTH high + 0.7 ATR → short next RTH open.", exitRules: "Target prior RTH close. Stop = overnight high + 0.3 ATR.", assetClass: "futures", devHandle: "", symbols: ["MCL"], seed: 43, sharpe: 1.04, winRate: 0.56, maxDD: 0.16, sample: 281, live: 142, subs: 487, avgR: 0.34 },
  { id: "s-mgc-trend", name: "MGC Asia Session Trend", description: "Asia-session trend following on micro gold futures.", longDescription: "Captures persistent Asia-session trends in gold using 15-minute Donchian channels.", entryRules: "20-bar Donchian breakout during Asia session, ATR(14) filter for noise.", exitRules: "Chandelier stop, exit at NY open.", assetClass: "futures", devHandle: "", symbols: ["MGC"], seed: 44, sharpe: 1.16, winRate: 0.47, maxDD: 0.18, sample: 354, live: 198, subs: 624, avgR: 0.62 },
];

const statusCycle: Strategy["status"][] = ["Watching", "In Position", "Cooldown"];

export const strategies: Strategy[] = stratDefs.map((d, i) => ({
  id: d.id,
  name: d.name,
  description: d.description,
  longDescription: d.longDescription,
  entryRules: d.entryRules,
  exitRules: d.exitRules,
  assetClass: d.assetClass,
  devHandle: "",
  symbols: d.symbols,
  status: statusCycle[i % 3],
  stage: "Published",
  edgeVerified: true,
  lastSignalAt: isoDaysAgo(Math.floor(i / 2), i * 3),
  createdAt: isoDaysAgo(180 + i * 12),
  stats: {
    sharpe: d.sharpe,
    winRate: d.winRate,
    maxDrawdown: d.maxDD,
    sampleSize: d.sample,
    avgR: d.avgR,
    liveDays: d.live,
    subscribers: d.subs,
  },
}));

/* ---------------- Equity curves ---------------- */
export function getEquityCurve(strategyId: string, days = 30): EquityPoint[] {
  const s = strategies.find((x) => x.id === strategyId);
  const seed = s ? s.stats.sampleSize + s.name.length : 7;
  const r = mulberry32(seed);
  const out: EquityPoint[] = [];
  let eq = 10000;
  for (let i = days - 1; i >= 0; i--) {
    const drift = ((s?.stats.sharpe ?? 1) / 200);
    const vol = 0.012;
    eq = eq * (1 + drift + (r() - 0.5) * vol);
    out.push({ t: isoDaysAgo(i), equity: Math.round(eq * 100) / 100 });
  }
  return out;
}

/* ---------------- Signals (Bayn catalog) ---------------- */
const symbolPrice: Record<string, number> = {
  AAPL: 228.4, MSFT: 432.1, NVDA: 138.2, AMZN: 198.3, META: 562.4,
  SPY: 583.1, IWM: 224.7, QQQ: 498.7,
  "BTC-PERP": 71240, "ETH-PERP": 3812, "SOL-USD": 178.5,
  MES: 5821.5, MNQ: 20418, MCL: 71.4, MGC: 2654,
};

function pickSymbol(s: Strategy, i: number) {
  if (s.symbols.length && symbolPrice[s.symbols[i % s.symbols.length]])
    return s.symbols[i % s.symbols.length];
  const fb: Record<AssetClass, string> = {
    stocks: "NVDA", crypto: "BTC-PERP", options: "SPY", futures: "MES",
  };
  return fb[s.assetClass];
}

function makeSeries(seed: number, base: number, n: number) {
  const arr = walk(seed, n, base, 0.006, 0);
  return arr.map((p, i) => ({ t: isoDaysAgo(0, n - i), price: Math.round(p * 100) / 100 }));
}

const statuses: Signal["status"][] = ["OPEN", "HIT_TARGET", "HIT_STOP", "EXPIRED"];

function buildSignal(strat: Strategy, i: number, idOffset = 1000): Signal {
  const sym = pickSymbol(strat, i);
  const base = symbolPrice[sym] ?? 100;
  const dir: Signal["direction"] = (i + (strat.name.length % 2)) % 3 === 0 ? "SHORT" : "LONG";
  const entry = Math.round(base * (1 + (i % 5 - 2) * 0.002) * 100) / 100;
  const stopPct = strat.assetClass === "crypto" ? 0.022 : strat.assetClass === "futures" ? 0.012 : 0.018;
  const targetPct = stopPct * 2.1;
  const stop = dir === "LONG" ? entry * (1 - stopPct) : entry * (1 + stopPct);
  const target = dir === "LONG" ? entry * (1 + targetPct) : entry * (1 - targetPct);
  const status = i < 6 ? "OPEN" : statuses[(i + 1) % 4];
  const firedAt = isoDaysAgo(i % 30, (i * 7) % 24);
  const series = makeSeries(strat.stats.sampleSize + i * 13, entry, 80);
  const reasoning = ({
    stocks: `${sym} cleared its opening range on 1.6× average volume with broad-market support; structure invites continuation toward the measured-move target.`,
    crypto: `${sym} extended 3.2σ above its 50-period VWAP into a low-liquidity window; historically this band reverts within 4 hours.`,
    options: `Front-week IV is rich vs back-month (1.42×) into a non-event week — short premium spreads carry positive expected value.`,
    futures: `${sym} faded its overnight gap inside 10 minutes — failed initiative signals fade-the-range setup with defined risk.`,
  } as const)[strat.assetClass];

  const extras: Partial<Signal> = {};
  if (strat.assetClass === "options") {
    extras.strike = Math.round(entry);
    extras.expiry = isoDaysAgo(-7 - (i % 21));
    extras.delta = 0.05 + ((i % 10) / 100);
    extras.iv = 0.18 + ((i % 30) / 200);
  }
  if (strat.assetClass === "futures") {
    extras.contractMonth = ["Dec '25", "Mar '26", "Jun '26"][i % 3];
    extras.tickSize = sym === "MES" ? 0.25 : sym === "MNQ" ? 0.25 : sym === "MCL" ? 0.01 : 0.1;
  }

  const closedAt = status === "OPEN" ? undefined : isoDaysAgo(Math.max(0, (i % 30) - 1), (i * 5) % 24);
  const pnlR =
    status === "HIT_TARGET" ? 2.1 :
    status === "HIT_STOP" ? -1.0 :
    status === "EXPIRED" ? (i % 2 === 0 ? 0.3 : -0.4) : undefined;

  return {
    id: `sig-${idOffset + i}`,
    strategyId: strat.id,
    strategyName: strat.name,
    assetClass: strat.assetClass,
    symbol: sym,
    direction: dir,
    entry: Math.round(entry * 100) / 100,
    stop: Math.round(stop * 100) / 100,
    target: Math.round(target * 100) / 100,
    status,
    firedAt,
    closedAt,
    pnlR,
    reasoning,
    priceSeries: series,
    ...extras,
  };
}

export const signals: Signal[] = Array.from({ length: 80 }).map((_, i) =>
  buildSignal(strategies[i % strategies.length], i)
);

/* ---------------- User performance ---------------- */
export function getUserEquityCurve(days = 30): EquityPoint[] {
  const r = mulberry32(99);
  const out: EquityPoint[] = [];
  let eq = 25000;
  for (let i = days - 1; i >= 0; i--) {
    eq *= 1 + 0.0025 + (r() - 0.45) * 0.012;
    out.push({ t: isoDaysAgo(i), equity: Math.round(eq * 100) / 100 });
  }
  return out;
}

export const takenSignals: TakenSignal[] = signals
  .filter((s) => s.status !== "OPEN")
  .slice(0, 24)
  .map((s, i) => ({
    id: `t-${i}`,
    signalId: s.id,
    signal: s,
    takenAt: s.firedAt,
    fillPrice: s.entry,
    pnlR: s.pnlR,
    outcome: s.status,
  }));

// Brand-new accounts start with zero followed strategies. Onboarding activates
// the four free verified strategies (one per asset class) into the overlay.
export const followedStrategyIds: string[] = [];

/* =================================================================
   STUDIO (developer-side) mock data
   ================================================================= */

/* Pre-built node graphs — five working strategy templates */

const graphMACross: DevStrategy["graph"] = {
  nodes: [
    { id: "n1", type: "price", category: "data", label: "Price (OHLCV)", position: { x: 40, y: 80 }, data: { symbol: "BTC-PERP", timeframe: "1h" } },
    { id: "n2", type: "sma", category: "indicator", label: "SMA Fast", position: { x: 320, y: 30 }, data: { period: 9, source: "close" } },
    { id: "n3", type: "sma", category: "indicator", label: "SMA Slow", position: { x: 320, y: 150 }, data: { period: 21, source: "close" } },
    { id: "n4", type: "crossover", category: "logic", label: "Crosses Above", position: { x: 600, y: 90 }, data: { op: "crosses_above" } },
    { id: "n5", type: "stopLoss", category: "risk", label: "ATR Stop", position: { x: 600, y: 230 }, data: { type: "atr", atrPeriod: 14, multiple: 2 } },
    { id: "n6", type: "entry", category: "signal", label: "Entry LONG", position: { x: 880, y: 140 }, data: { direction: "LONG" } },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n2" },
    { id: "e2", source: "n1", target: "n3" },
    { id: "e3", source: "n2", target: "n4", targetHandle: "a" },
    { id: "e4", source: "n3", target: "n4", targetHandle: "b" },
    { id: "e5", source: "n4", target: "n6" },
    { id: "e6", source: "n5", target: "n6" },
  ],
};

const graphRSIMR: DevStrategy["graph"] = {
  nodes: [
    { id: "n1", type: "price", category: "data", label: "Price", position: { x: 40, y: 100 }, data: { symbol: "SPY", timeframe: "1d" } },
    { id: "n2", type: "rsi", category: "indicator", label: "RSI(2)", position: { x: 320, y: 60 }, data: { period: 2 } },
    { id: "n3", type: "sma", category: "indicator", label: "SMA 200", position: { x: 320, y: 180 }, data: { period: 200 } },
    { id: "n4", type: "comparator", category: "logic", label: "RSI < 10", position: { x: 600, y: 60 }, data: { op: "<", value: 10 } },
    { id: "n5", type: "comparator", category: "logic", label: "Price > SMA200", position: { x: 600, y: 180 }, data: { op: ">", value: 0 } },
    { id: "n6", type: "and", category: "logic", label: "AND", position: { x: 860, y: 120 }, data: {} },
    { id: "n7", type: "entry", category: "signal", label: "Entry LONG", position: { x: 1120, y: 120 }, data: { direction: "LONG" } },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n2" },
    { id: "e2", source: "n1", target: "n3" },
    { id: "e3", source: "n2", target: "n4" },
    { id: "e4", source: "n3", target: "n5" },
    { id: "e5", source: "n4", target: "n6", targetHandle: "a" },
    { id: "e6", source: "n5", target: "n6", targetHandle: "b" },
    { id: "e7", source: "n6", target: "n7" },
  ],
};

const graphBBBreakout: DevStrategy["graph"] = {
  nodes: [
    { id: "n1", type: "price", category: "data", label: "Price", position: { x: 40, y: 80 }, data: { symbol: "NVDA", timeframe: "15m" } },
    { id: "n2", type: "bb", category: "indicator", label: "Bollinger Bands", position: { x: 320, y: 80 }, data: { period: 20, stdDev: 2 } },
    { id: "n3", type: "crossover", category: "logic", label: "Crosses Above Upper", position: { x: 600, y: 80 }, data: { op: "crosses_above" } },
    { id: "n4", type: "stopLoss", category: "risk", label: "Stop", position: { x: 600, y: 220 }, data: { type: "percent", value: 1.5 } },
    { id: "n5", type: "takeProfit", category: "risk", label: "Target", position: { x: 600, y: 320 }, data: { type: "r_multiple", value: 2 } },
    { id: "n6", type: "entry", category: "signal", label: "Entry LONG", position: { x: 900, y: 180 }, data: { direction: "LONG" } },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n2" },
    { id: "e2", source: "n2", target: "n3" },
    { id: "e3", source: "n3", target: "n6" },
    { id: "e4", source: "n4", target: "n6" },
    { id: "e5", source: "n5", target: "n6" },
  ],
};

const graphORB: DevStrategy["graph"] = {
  nodes: [
    { id: "n1", type: "price", category: "data", label: "Price 5m", position: { x: 40, y: 80 }, data: { symbol: "ES", timeframe: "5m" } },
    { id: "n2", type: "volume", category: "data", label: "Volume", position: { x: 40, y: 220 }, data: {} },
    { id: "n3", type: "timeWindow", category: "logic", label: "After 10:00 ET", position: { x: 320, y: 80 }, data: { start: "10:00", end: "15:45" } },
    { id: "n4", type: "comparator", category: "logic", label: "Vol > 1.4× avg", position: { x: 320, y: 220 }, data: { op: ">", value: 1.4 } },
    { id: "n5", type: "and", category: "logic", label: "AND", position: { x: 620, y: 140 }, data: {} },
    { id: "n6", type: "stopLoss", category: "risk", label: "Range Low", position: { x: 620, y: 300 }, data: { type: "structure" } },
    { id: "n7", type: "entry", category: "signal", label: "Entry LONG", position: { x: 900, y: 200 }, data: { direction: "LONG" } },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n3" },
    { id: "e2", source: "n2", target: "n4" },
    { id: "e3", source: "n3", target: "n5", targetHandle: "a" },
    { id: "e4", source: "n4", target: "n5", targetHandle: "b" },
    { id: "e5", source: "n5", target: "n7" },
    { id: "e6", source: "n6", target: "n7" },
  ],
};

const graphOptionsSell: DevStrategy["graph"] = {
  nodes: [
    { id: "n1", type: "optionsChain", category: "data", label: "SPY Options Chain", position: { x: 40, y: 80 }, data: { symbol: "SPY" } },
    { id: "n2", type: "comparator", category: "logic", label: "VIX < median60", position: { x: 320, y: 80 }, data: { op: "<", value: 0 } },
    { id: "n3", type: "timeWindow", category: "logic", label: "7 DTE", position: { x: 320, y: 220 }, data: { dte: 7 } },
    { id: "n4", type: "and", category: "logic", label: "AND", position: { x: 620, y: 150 }, data: {} },
    { id: "n5", type: "positionSize", category: "risk", label: "Size 2%", position: { x: 620, y: 300 }, data: { type: "percent_account", value: 2 } },
    { id: "n6", type: "entry", category: "signal", label: "Sell 5Δ Put Spread", position: { x: 900, y: 200 }, data: { direction: "SHORT", structure: "put_spread", delta: 5 } },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n2" },
    { id: "e2", source: "n1", target: "n3" },
    { id: "e3", source: "n2", target: "n4", targetHandle: "a" },
    { id: "e4", source: "n3", target: "n4", targetHandle: "b" },
    { id: "e5", source: "n4", target: "n6" },
    { id: "e6", source: "n5", target: "n6" },
  ],
};

export const graphTemplates: Array<{ id: string; name: string; assetClass: AssetClass; description: string; graph: DevStrategy["graph"] }> = [
  { id: "tpl-ma", name: "Moving Average Crossover", assetClass: "crypto", description: "Classic fast/slow SMA cross with ATR stop.", graph: graphMACross },
  { id: "tpl-rsi", name: "RSI Mean Reversion", assetClass: "stocks", description: "Larry Connors-style RSI(2) under uptrend filter.", graph: graphRSIMR },
  { id: "tpl-bb", name: "Bollinger Band Breakout", assetClass: "stocks", description: "Volatility breakout with R-multiple target.", graph: graphBBBreakout },
  { id: "tpl-orb", name: "Opening Range Breakout", assetClass: "futures", description: "Time-windowed opening range with volume confirmation.", graph: graphORB },
  { id: "tpl-opt", name: "Options Premium Selling", assetClass: "options", description: "Sells short-dated OTM put spreads in low-VIX regimes.", graph: graphOptionsSell },
];

export const devStrategies: DevStrategy[] = [
  {
    id: "dev-1",
    name: "BTC Hourly MA Cross — Personal",
    description: "My take on a 9/21 SMA cross on BTC with ATR stop, tuned for hourly.",
    assetClass: "crypto",
    stage: "Live",
    createdAt: isoDaysAgo(74),
    lastRunAt: isoDaysAgo(1, 4),
    graph: graphMACross,
    liveSinceDays: 41,
    stats: { sharpe: 1.18, winRate: 0.51, maxDrawdown: 0.12, sampleSize: 184, avgR: 0.42, liveDays: 41, subscribers: 0 },
    versions: [
      { id: "v3", createdAt: isoDaysAgo(2), note: "Tightened ATR multiple to 2.0" },
      { id: "v2", createdAt: isoDaysAgo(18), note: "Added cooldown of 6 bars" },
      { id: "v1", createdAt: isoDaysAgo(74), note: "Initial draft" },
    ],
  },
  {
    id: "dev-2",
    name: "SPY RSI(2) Reversion",
    description: "Connors-style mean reversion for SPY.",
    assetClass: "stocks",
    stage: "Forward Testing",
    createdAt: isoDaysAgo(42),
    lastRunAt: isoDaysAgo(0, 7),
    graph: graphRSIMR,
    liveSinceDays: 18,
    stats: { sharpe: 0.96, winRate: 0.69, maxDrawdown: 0.07, sampleSize: 38, avgR: 0.22, liveDays: 18, subscribers: 0 },
    versions: [
      { id: "v2", createdAt: isoDaysAgo(12), note: "Lowered RSI threshold to 8" },
      { id: "v1", createdAt: isoDaysAgo(42), note: "Initial" },
    ],
  },
  {
    id: "dev-3",
    name: "NVDA 15m BB Breakout",
    description: "Bollinger expansion on NVDA intraday.",
    assetClass: "stocks",
    stage: "Backtested",
    createdAt: isoDaysAgo(21),
    lastRunAt: isoDaysAgo(3),
    graph: graphBBBreakout,
    stats: { sharpe: 1.42, winRate: 0.48, maxDrawdown: 0.14, sampleSize: 312, avgR: 0.71, liveDays: 0, subscribers: 0 },
    versions: [
      { id: "v1", createdAt: isoDaysAgo(21), note: "Initial draft" },
    ],
  },
  {
    id: "dev-4",
    name: "ES Opening Range — Experiment",
    description: "Volume-confirmed ORB on ES, intraday only.",
    assetClass: "futures",
    stage: "Draft",
    createdAt: isoDaysAgo(6),
    graph: graphORB,
    versions: [
      { id: "v1", createdAt: isoDaysAgo(6), note: "Sketch" },
    ],
  },
  {
    id: "dev-5",
    name: "SPY Weekly Put Spreads",
    description: "Short 5-delta SPY weekly put spreads in low VIX.",
    assetClass: "options",
    stage: "Submitted",
    createdAt: isoDaysAgo(112),
    lastRunAt: isoDaysAgo(8),
    graph: graphOptionsSell,
    liveSinceDays: 64,
    stats: { sharpe: 1.51, winRate: 0.81, maxDrawdown: 0.11, sampleSize: 96, avgR: 0.19, liveDays: 64, subscribers: 0 },
    submissionStatus: "Human Review",
    submissionNotes: "Pipeline validation passed. Awaiting reviewer notes on edge-case behavior during VIX spikes >35.",
    versions: [
      { id: "v4", createdAt: isoDaysAgo(8), note: "Added daily loss cap" },
      { id: "v3", createdAt: isoDaysAgo(40), note: "Roll rule on tested side" },
      { id: "v2", createdAt: isoDaysAgo(70), note: "Term structure filter" },
      { id: "v1", createdAt: isoDaysAgo(112), note: "Initial draft" },
    ],
  },
];

/* ---- Personal signals (only from dev's own strategies) ---- */
export const personalSignals: PersonalSignal[] = Array.from({ length: 22 }).map((_, i) => {
  const d = devStrategies[i % devStrategies.length];
  const stratLike: Strategy = {
    id: d.id, name: d.name, description: d.description, longDescription: d.description,
    entryRules: "", exitRules: "", assetClass: d.assetClass, devHandle: "", symbols: [],
    status: "Watching", stage: d.stage, edgeVerified: false, lastSignalAt: isoDaysAgo(0),
    createdAt: d.createdAt,
    stats: d.stats ?? { sharpe: 1, winRate: 0.5, maxDrawdown: 0.1, sampleSize: 100, avgR: 0.3, liveDays: 30, subscribers: 0 },
  };
  const s = buildSignal(stratLike, i + 200, 5000);
  return { ...s, ownStrategyId: d.id, ownStrategyName: d.name };
});

/* ---- Backtest runs ---- */
function buildBacktest(strategyId: string, seed: number, idx: number): BacktestRun {
  const r = mulberry32(seed);
  const equity: EquityPoint[] = [];
  let eq = 25000;
  const days = 365;
  for (let i = days - 1; i >= 0; i--) {
    eq *= 1 + 0.0009 + (r() - 0.48) * 0.014;
    equity.push({ t: isoDaysAgo(i + 30), equity: Math.round(eq * 100) / 100 });
  }
  const totalRet = equity[equity.length - 1].equity / 25000 - 1;
  const trades = Array.from({ length: 60 + Math.floor(r() * 60) }).map((_, i) => {
    const entryDate = isoDaysAgo(365 - i * 5);
    const exitDate = isoDaysAgo(365 - i * 5 - 2);
    const win = r() > 0.45;
    const pnlR = win ? 1.5 + r() * 1.5 : -(0.8 + r() * 0.4);
    return {
      id: `bt-tr-${idx}-${i}`,
      entryDate, exitDate,
      symbol: ["BTC-PERP", "SPY", "NVDA", "ES"][i % 4],
      direction: (i % 3 === 0 ? "SHORT" : "LONG") as "LONG" | "SHORT",
      entry: 100 + r() * 50,
      exit: 100 + r() * 50,
      pnlPct: pnlR * 0.012,
      pnlR,
    };
  });
  const wins = trades.filter((t) => t.pnlR > 0);
  const losses = trades.filter((t) => t.pnlR <= 0);
  let peak = -Infinity, dd = 0;
  for (const p of equity) { peak = Math.max(peak, p.equity); dd = Math.min(dd, (p.equity - peak) / peak); }

  const monthlyReturns: BacktestRun["monthlyReturns"] = [];
  for (let m = 11; m >= 0; m--) {
    const d = new Date(); d.setMonth(d.getMonth() - m);
    monthlyReturns.push({ month: d.toISOString().slice(0, 7), ret: (r() - 0.42) * 0.08 });
  }

  return {
    id: `bt-${strategyId}-${idx}`,
    strategyId,
    ranAt: isoDaysAgo(idx * 7 + 1),
    params: { startDate: "2023-01-01", endDate: "2024-12-31", capital: 25000, commissionBps: 5, slippageBps: 3 },
    stats: {
      totalReturn: totalRet,
      cagr: Math.pow(1 + totalRet, 365 / days) - 1,
      sharpe: 0.8 + r() * 1.6,
      sortino: 1.0 + r() * 1.8,
      maxDrawdown: dd,
      winRate: wins.length / trades.length,
      profitFactor: wins.reduce((s, t) => s + t.pnlR, 0) / Math.max(0.1, -losses.reduce((s, t) => s + t.pnlR, 0)),
      avgWin: wins.reduce((s, t) => s + t.pnlR, 0) / Math.max(1, wins.length),
      avgLoss: losses.reduce((s, t) => s + t.pnlR, 0) / Math.max(1, losses.length),
      avgHoldDays: 2 + Math.floor(r() * 4),
      totalTrades: trades.length,
    },
    equity,
    trades,
    monthlyReturns,
  };
}

export const backtestRuns: BacktestRun[] = devStrategies.flatMap((d, i) => [
  buildBacktest(d.id, 100 + i * 7, 0),
  buildBacktest(d.id, 200 + i * 7, 1),
  buildBacktest(d.id, 300 + i * 7, 2),
]);

/* ---- Studio earnings (mock for the one accepted strategy) ---- */
export const studioEarnings: StudioEarning[] = Array.from({ length: 6 }).map((_, i) => {
  const d = new Date(); d.setMonth(d.getMonth() - i);
  const month = d.toISOString().slice(0, 7);
  return {
    month,
    strategyId: "dev-5",
    strategyName: "SPY Weekly Put Spreads",
    amount: Math.round((1200 - i * 80 + Math.sin(i) * 100) * 100) / 100,
    subscribers: Math.max(20, 180 - i * 15),
  };
}).reverse();

/* ---------------- Market news (Bloomberg-style ticker) ---------------- */
export interface NewsItem {
  id: string;
  source: string;
  headline: string;
  symbol?: string;
  category: "Markets" | "Crypto" | "Macro" | "Earnings" | "Energy" | "Rates";
  sentiment: "pos" | "neg" | "neu";
  minutesAgo: number;
}
export const marketNews: NewsItem[] = [
  { id: "n1", source: "Reuters", category: "Markets", sentiment: "pos", minutesAgo: 2, symbol: "SPY", headline: "S&P 500 extends rally on cooling inflation print" },
  { id: "n2", source: "Bloomberg", category: "Earnings", sentiment: "pos", minutesAgo: 6, symbol: "NVDA", headline: "Nvidia data-center bookings exceed Q4 consensus by 11%" },
  { id: "n3", source: "WSJ", category: "Rates", sentiment: "neu", minutesAgo: 14, headline: "Fed minutes show split on timing of next rate cut" },
  { id: "n4", source: "CoinDesk", category: "Crypto", sentiment: "neg", minutesAgo: 18, symbol: "BTC", headline: "Bitcoin slips below 71k as ETF outflows accelerate" },
  { id: "n5", source: "Bloomberg", category: "Energy", sentiment: "neg", minutesAgo: 22, symbol: "CL", headline: "Crude oil tests $71 on demand-cut warning from IEA" },
  { id: "n6", source: "FT", category: "Macro", sentiment: "neu", minutesAgo: 31, headline: "ECB signals patience as core inflation stays sticky" },
  { id: "n7", source: "Reuters", category: "Earnings", sentiment: "pos", minutesAgo: 38, symbol: "AAPL", headline: "Apple services revenue hits record on subscriptions" },
  { id: "n8", source: "Bloomberg", category: "Crypto", sentiment: "pos", minutesAgo: 47, symbol: "ETH", headline: "Ethereum staking yield rises to 4.1% after upgrade" },
  { id: "n9", source: "WSJ", category: "Markets", sentiment: "neg", minutesAgo: 54, symbol: "VIX", headline: "Volatility curve flattens — dealers signal hedge demand" },
  { id: "n10", source: "Reuters", category: "Macro", sentiment: "neu", minutesAgo: 62, headline: "US payrolls preview: street looks for 175k, 4.1% unemployment" },
  { id: "n11", source: "Bloomberg", category: "Earnings", sentiment: "neg", minutesAgo: 71, symbol: "META", headline: "Meta capex guide rattles ad-tech peers in after-hours" },
  { id: "n12", source: "CoinDesk", category: "Crypto", sentiment: "neu", minutesAgo: 80, headline: "Stablecoin supply tops $170B as Treasury yields hold" },
];

export function getMarketNews() { return marketNews; }
