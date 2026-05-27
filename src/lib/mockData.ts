import type {
  Strategy, Signal, MarketTile, EquityPoint, TakenSignal, AssetClass,
} from "./types";

/* Deterministic PRNG so charts don't dance between renders */
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
  { symbol: "SPY",  label: "S&P 500 ETF",  assetClass: "stocks", price: 583.12, changePct:  0.42, spark: walk(1, 30, 580, 0.004,  0.0005) },
  { symbol: "QQQ",  label: "Nasdaq 100",   assetClass: "stocks", price: 498.77, changePct:  0.68, spark: walk(2, 30, 495, 0.006,  0.0008) },
  { symbol: "BTC",  label: "Bitcoin",      assetClass: "crypto", price: 71240,  changePct: -1.12, spark: walk(3, 30, 72500, 0.012, -0.0004) },
  { symbol: "ETH",  label: "Ethereum",     assetClass: "crypto", price: 3812,   changePct:  2.04, spark: walk(4, 30, 3700, 0.015,  0.0012) },
  { symbol: "ES",   label: "S&P Futures",  assetClass: "futures", price: 5821.5, changePct: 0.31, spark: walk(5, 30, 5810, 0.004, 0.0003) },
  { symbol: "VIX",  label: "Volatility",   assetClass: "index" as AssetClass, price: 13.84, changePct: -3.42, spark: walk(6, 30, 15, 0.03, -0.003) },
];

/* ---------------- Strategies ---------------- */
type SDef = Omit<Strategy, "stats" | "lastSignalAt" | "createdAt" | "status" | "edgeVerified" | "stage"> & {
  seed: number; sharpe: number; winRate: number; maxDD: number; sample: number; live: number; subs: number; avgR: number;
};

const stratDefs: SDef[] = [
  // Stocks
  { id: "s-ore-es", name: "Opening Range Breakout — Mega Caps", description: "First 30-min range breakout on liquid large caps with volume confirmation.", longDescription: "Trades the breakout of the first 30-minute range on a curated basket of mega-cap equities (AAPL, MSFT, NVDA, AMZN, META). Long-only.", entryRules: "After 10:00 ET, if price closes above the 9:30–10:00 range high on >1.4x average opening volume, enter long.", exitRules: "Stop = range low. Target = 2x range height. Time stop at 15:45 ET.", assetClass: "stocks", devHandle: "@quietsignal", symbols: ["AAPL","MSFT","NVDA","AMZN","META"], seed: 11, sharpe: 1.42, winRate: 0.54, maxDD: 0.11, sample: 612, live: 184, subs: 1247, avgR: 0.38 },
  { id: "s-earn-drift", name: "Earnings Drift — Mid-Cap Tech", description: "Post-earnings drift on mid-cap tech beats with strong guidance.", longDescription: "Buys mid-cap tech names ($2B–$20B) the morning after an earnings beat where guidance was raised and the stock gapped between 3% and 9%.", entryRules: "Beat EPS by >5%, raised forward guidance, gap open between +3% and +9% on >2x avg volume.", exitRules: "Stop = gap-fill level. Target = +12% from entry. Time stop = 10 trading days.", assetClass: "stocks", devHandle: "@drift_lab", symbols: ["mid-cap tech basket"], seed: 12, sharpe: 1.81, winRate: 0.61, maxDD: 0.14, sample: 287, live: 312, subs: 894, avgR: 0.71 },
  { id: "s-meanrev-spy", name: "Mean Reversion — SPY 2-Day", description: "Buys SPY oversold 2-day RSI extremes in established uptrends.", longDescription: "A classic Larry Connors-style mean reversion: only trades when SPY is above its 200-day SMA and 2-day RSI prints below 10.", entryRules: "SPY > 200 SMA AND RSI(2) < 10 at close — enter long next open.", exitRules: "Exit when RSI(2) > 70 OR after 5 trading days, whichever first.", assetClass: "stocks", devHandle: "@thesis_eight", symbols: ["SPY"], seed: 13, sharpe: 1.08, winRate: 0.67, maxDD: 0.08, sample: 451, live: 421, subs: 2103, avgR: 0.22 },

  // Crypto
  { id: "s-btc-hourly-mr", name: "Mean Reversion — BTC Hourly", description: "Hourly BTC fades of 3-sigma deviations from the 50-period VWAP.", longDescription: "Fades extreme hourly deviations from VWAP on BTC perpetual. Trades both sides. Skips trading during NYSE open ±15 min.", entryRules: "Price > 3σ above 50-hour VWAP → short. Price < 3σ below → long.", exitRules: "Target = VWAP. Stop = 1.5x entry deviation.", assetClass: "crypto", devHandle: "@vega_room", symbols: ["BTC-PERP"], seed: 21, sharpe: 1.64, winRate: 0.58, maxDD: 0.17, sample: 1284, live: 198, subs: 3412, avgR: 0.41 },
  { id: "s-eth-mom", name: "Momentum Continuation — ETH 4H", description: "Buys ETH 4-hour higher-high breakouts confirmed by funding flip.", longDescription: "Catches established ETH uptrends on the 4-hour by entering on a higher-high breakout that aligns with funding flipping positive.", entryRules: "4H higher high after 3 consecutive higher lows AND funding > 0.005%.", exitRules: "Trail stop at prior swing low. No fixed target.", assetClass: "crypto", devHandle: "@chainmuse", symbols: ["ETH-PERP"], seed: 22, sharpe: 1.21, winRate: 0.46, maxDD: 0.21, sample: 318, live: 256, subs: 1782, avgR: 0.84 },
  { id: "s-sol-vol", name: "Volatility Breakout — SOL Daily", description: "Daily volatility expansion on SOL with regime filter.", longDescription: "Trades daily volatility expansion on SOL when realized volatility compresses below its 30-day median and breaks out.", entryRules: "30D realized vol < 30D median × 0.7 AND daily close > prior 5-day high.", exitRules: "Chandelier stop, ATR(14) × 3. Time stop 21 days.", assetClass: "crypto", devHandle: "@sigmaforge", symbols: ["SOL-USD"], seed: 23, sharpe: 0.94, winRate: 0.41, maxDD: 0.23, sample: 204, live: 147, subs: 612, avgR: 0.96 },

  // Options
  { id: "s-spy-otm-put", name: "Far-OTM Weekly Premium — SPY", description: "Sells 5-delta SPY weekly puts in low-VIX regimes.", longDescription: "Sells 5-delta SPY weekly puts when VIX is below its 60-day median and the term structure is in contango. Defined-risk via a 1-strike wide spread.", entryRules: "VIX < 60D median AND VX1/VX2 < 1.0. Sell 5-delta weekly put spread (1 strike wide), 7 DTE.", exitRules: "Close at 50% max profit or 21 DTE, whichever first. Stop at 2x credit.", assetClass: "options", devHandle: "@theta_diary", symbols: ["SPY"], seed: 31, sharpe: 1.36, winRate: 0.83, maxDD: 0.12, sample: 244, live: 392, subs: 1521, avgR: 0.18 },
  { id: "s-iwm-iron-condor", name: "IWM Iron Condor — 30 DTE", description: "Monthly 16-delta iron condors on IWM with rolling rules.", longDescription: "Sells 16-delta iron condors on IWM at 30–45 DTE with mechanical roll rules on tested sides.", entryRules: "On first trading day each month: open 16-delta iron condor, 30–45 DTE, wings 4 strikes wide.", exitRules: "Close at 50% max profit. Roll tested side once at 21 DTE if challenged.", assetClass: "options", devHandle: "@condor_co", symbols: ["IWM"], seed: 32, sharpe: 0.88, winRate: 0.72, maxDD: 0.19, sample: 198, live: 271, subs: 478, avgR: 0.21 },
  { id: "s-nvda-call-diag", name: "NVDA Call Diagonal — Earnings", description: "Diagonal calls into NVDA earnings exploiting term-structure skew.", longDescription: "Long a 60 DTE call, short a 7 DTE call, structured a week before NVDA earnings to harvest front-week IV crush.", entryRules: "7 calendar days before NVDA earnings, when front-week IV / back-month IV > 1.35.", exitRules: "Close day after earnings regardless of outcome.", assetClass: "options", devHandle: "@vol_pilot", symbols: ["NVDA"], seed: 33, sharpe: 1.92, winRate: 0.58, maxDD: 0.18, sample: 64, live: 102, subs: 311, avgR: 1.12 },

  // Futures
  { id: "s-mes-orb", name: "MES Opening Range Reversal", description: "Fades the MES opening range when overnight gap is faded.", longDescription: "Fades the opening 15-minute range on MES when the overnight gap is closed in the first 10 minutes — a sign of failed initiative.", entryRules: "Overnight gap closes within first 10 minutes. Enter at break of opposite end of 15-min range.", exitRules: "Stop = range high (or low for longs). Target = 1.5x range height.", assetClass: "futures", devHandle: "@pit_minus", symbols: ["MES"], seed: 41, sharpe: 1.27, winRate: 0.52, maxDD: 0.13, sample: 488, live: 167, subs: 921, avgR: 0.44 },
  { id: "s-mnq-trend", name: "MNQ Trend-Day Continuation", description: "Catches MNQ trend-day legs after a confirmed midday breakout.", longDescription: "Identifies trend days on MNQ by midday range characteristics and enters on the first pullback after a 12:00 ET breakout.", entryRules: "12:00 ET breakout of midday range, then first pullback to VWAP that holds.", exitRules: "Trail under each 15-min swing low. Hard stop at VWAP loss.", assetClass: "futures", devHandle: "@tape_reader", symbols: ["MNQ"], seed: 42, sharpe: 1.55, winRate: 0.49, maxDD: 0.15, sample: 372, live: 211, subs: 1334, avgR: 0.82 },
  { id: "s-mcl-overnight", name: "MCL Overnight Inventory", description: "MCL overnight inventory fade based on RTH closing range.", longDescription: "Fades MCL overnight inventory imbalances back to the prior RTH close when overnight extends beyond the prior day's range by >0.7 ATR.", entryRules: "Overnight high > prior RTH high + 0.7 ATR → short next RTH open.", exitRules: "Target prior RTH close. Stop = overnight high + 0.3 ATR.", assetClass: "futures", devHandle: "@inventory", symbols: ["MCL"], seed: 43, sharpe: 1.04, winRate: 0.56, maxDD: 0.16, sample: 281, live: 142, subs: 487, avgR: 0.34 },
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
  devHandle: d.devHandle,
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

/* ---------------- Equity curves per strategy ---------------- */
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

/* ---------------- Signals ---------------- */
const symbolPrice: Record<string, number> = {
  AAPL: 228.4, MSFT: 432.1, NVDA: 138.2, AMZN: 198.3, META: 562.4,
  SPY: 583.1, IWM: 224.7, QQQ: 498.7,
  "BTC-PERP": 71240, "ETH-PERP": 3812, "SOL-USD": 178.5,
  MES: 5821.5, MNQ: 20418, MCL: 71.4, MGC: 2654,
};

function pickSymbol(s: Strategy, i: number) {
  if (s.symbols.length && symbolPrice[s.symbols[i % s.symbols.length]])
    return s.symbols[i % s.symbols.length];
  // fallback per asset class
  const fb: Record<AssetClass, string> = {
    stocks: "NVDA", crypto: "BTC-PERP", options: "SPY", futures: "MES",
  };
  return fb[s.assetClass];
}

function makeSeries(seed: number, base: number, n: number) {
  const arr = walk(seed, n, base, 0.006, 0);
  return arr.map((p, i) => ({
    t: isoDaysAgo(0, n - i),
    price: Math.round(p * 100) / 100,
  }));
}

const statuses: Signal["status"][] = ["OPEN", "HIT_TARGET", "HIT_STOP", "EXPIRED"];

export const signals: Signal[] = Array.from({ length: 60 }).map((_, i) => {
  const strat = strategies[i % strategies.length];
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
    id: `sig-${1000 + i}`,
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
});

/* User performance ---------------- */
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

export const followedStrategyIds = strategies.slice(0, 6).map((s) => s.id);
