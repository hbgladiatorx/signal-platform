/**
 * Billing — mocked plan catalog, add-ons, usage and current state.
 * Structured so it can swap for real Stripe + Supabase later: every read
 * goes through getCurrentPlan/getUsage rather than touching constants.
 */

import { logDebugEvent } from "@/lib/debug-log";

export type Audience = "trader" | "developer";
export type Billing = "monthly" | "annual";

export type TierId =
  | "trader-signal" | "trader-edge" | "trader-desk"
  | "studio-builder" | "studio-quant" | "studio-principal";

export type Feature = { label: string; emphasis?: boolean };

export type Tier = {
  id: TierId;
  audience: Audience;
  name: string;
  blurb: string;          // "what it's for" one-liner
  monthly: number;        // USD / mo
  highlight?: boolean;    // most popular
  cta: string;
  /** Strategy/active slot count baked into the tier; -1 = unlimited */
  includedSlots: number;
  features: Feature[];
  meta?: { backtestRuns?: number; backtestYears?: number; aiBuilds?: number; liveStrategies?: number };
};

export type AddOn = {
  id: string;
  audience: Audience;
  name: string;
  description: string;
  price: number;          // USD / mo
  unit?: string;          // "per slot" etc.
  availableOn?: TierId[]; // restrict to specific tiers
  includedOn?: TierId[];  // baked in at higher tiers
};

/* ---------------- Tiers ---------------- */

export const TIERS: Tier[] = [
  // Trader
  {
    id: "trader-signal", audience: "trader", name: "Signal", blurb: "Verified signals for serious individual traders.",
    monthly: 149, cta: "Start with Signal", includedSlots: 3,
    features: [
      { label: "4 free verified strategies, always included", emphasis: true },
      { label: "3 premium catalog strategies of your choice" },
      { label: "Full signal feed: charts, entry/stop/target, reasoning" },
      { label: "Performance tracking + verified share cards" },
      { label: "Trader-mode AI analysis (50 queries/mo)" },
      { label: "1 connected broker / agent" },
    ],
  },
  {
    id: "trader-edge", audience: "trader", name: "Edge", blurb: "Full agentic loop. Built for active operators.",
    monthly: 349, highlight: true, cta: "Move up to Edge", includedSlots: 10,
    features: [
      { label: "Everything in Signal" },
      { label: "10 premium catalog strategies", emphasis: true },
      { label: "Trader-mode AI analysis (unlimited)" },
      { label: "Full agentic loop: Bayn MCP + Robinhood Agentic + all broker connections", emphasis: true },
      { label: "Priority signal delivery" },
      { label: "Advanced performance analytics (by asset class, R-multiple, drawdown)" },
    ],
  },
  {
    id: "trader-desk", audience: "trader", name: "Desk", blurb: "Institutional access for the full catalog.",
    monthly: 799, cta: "Open the Desk", includedSlots: -1,
    features: [
      { label: "Everything in Edge" },
      { label: "Unlimited catalog strategies", emphasis: true },
      { label: "Early access to newly published strategies" },
      { label: "Custom alerting + webhook delivery" },
      { label: "Dedicated onboarding session" },
      { label: "Priority support" },
    ],
  },
  // Studio
  {
    id: "studio-builder", audience: "developer", name: "Builder", blurb: "The lab. Build and forward-test your own strategies.",
    monthly: 299, cta: "Build with Builder", includedSlots: 5,
    features: [
      { label: "Node-based strategy builder (full node library)" },
      { label: "AI strategy construction — describe → graph (30 builds/mo)" },
      { label: "5 active strategies" },
      { label: "Backtesting: 50 runs/mo, 5 years of history" },
      { label: "Out-of-sample testing" },
      { label: "Live forward-test: 2 strategies running" },
      { label: "Personal signal feed + agentic execution" },
      { label: "Export strategy JSON" },
    ],
    meta: { backtestRuns: 50, backtestYears: 5, aiBuilds: 30, liveStrategies: 2 },
  },
  {
    id: "studio-quant", audience: "developer", name: "Quant", blurb: "Desk-grade research and validation.",
    monthly: 699, highlight: true, cta: "Run as a Quant", includedSlots: -1,
    features: [
      { label: "Everything in Builder" },
      { label: "Unlimited strategies", emphasis: true },
      { label: "AI strategy construction — unlimited builds" },
      { label: "Backtesting: unlimited runs, 15 years, all asset classes", emphasis: true },
      { label: "Live forward-test: 10 strategies simultaneously" },
      { label: "Walk-forward optimization + Monte Carlo robustness" },
      { label: "Multi-timeframe + multi-asset strategies" },
      { label: "Submit strategies to Bayn for catalog review (revenue share eligible)", emphasis: true },
    ],
    meta: { backtestRuns: -1, backtestYears: 15, aiBuilds: -1, liveStrategies: 10 },
  },
  {
    id: "studio-principal", audience: "developer", name: "Principal", blurb: "Tick-level data, top revenue share, direct review channel.",
    monthly: 1499, cta: "Take Principal", includedSlots: -1,
    features: [
      { label: "Everything in Quant" },
      { label: "Unlimited live forward-test strategies" },
      { label: "Full historical depth + tick-level backtest data", emphasis: true },
      { label: "Custom indicator / formula node SDK" },
      { label: "Highest backtest compute priority" },
      { label: "Direct Bayn review channel (faster turnaround)" },
      { label: "Top-tier revenue share on published strategies", emphasis: true },
      { label: "1:1 strategy consultation" },
    ],
    meta: { backtestRuns: -1, backtestYears: 25, aiBuilds: -1, liveStrategies: -1 },
  },
];

/* ---------------- Add-ons ---------------- */

export const ADDONS: AddOn[] = [
  // Trader
  { id: "trader-extra-strategy", audience: "trader", name: "Extra strategy slot",
    description: "Add one more catalog subscription beyond your tier allotment.",
    price: 99, unit: "/ slot / mo" },
  { id: "trader-strategy-pack-5", audience: "trader", name: "Strategy pack — 5 slots",
    description: "Five additional catalog subscriptions. Volume discount.",
    price: 399, unit: "/ mo" },
  { id: "trader-extra-broker", audience: "trader", name: "Additional broker / agent connection",
    description: "Connect another brokerage or AI agent.",
    price: 29, unit: "/ connection / mo",
    availableOn: ["trader-signal"], includedOn: ["trader-edge", "trader-desk"] },
  { id: "trader-history-export", audience: "trader", name: "Extended history export",
    description: "Full trade-level CSV, tax-ready, including closed strategies.",
    price: 19, unit: "/ mo" },
  // Studio
  { id: "studio-live-slot", audience: "developer", name: "Additional live strategy slot",
    description: "Run another strategy live alongside your tier allotment.",
    price: 79, unit: "/ slot / mo",
    availableOn: ["studio-builder", "studio-quant"] },
  { id: "studio-compute", audience: "developer", name: "Extended backtest compute",
    description: "Priority queue + larger symbol universes for parameter sweeps.",
    price: 149, unit: "/ mo" },
  { id: "studio-tick-data", audience: "developer", name: "Tick-level data pack",
    description: "Microstructure-grade tick data for entry/exit validation.",
    price: 199, unit: "/ mo",
    availableOn: ["studio-builder", "studio-quant"], includedOn: ["studio-principal"] },
];

/* ---------------- Helpers ---------------- */

export function tiersFor(audience: Audience): Tier[] {
  return TIERS.filter((t) => t.audience === audience);
}
export function addonsFor(audience: Audience): AddOn[] {
  return ADDONS.filter((a) => a.audience === audience);
}
export function getTier(id: TierId): Tier | undefined {
  return TIERS.find((t) => t.id === id);
}

/** Annual price = 10× monthly (2 months free). Display helper. */
export function priceFor(tier: Tier, billing: Billing): { perMonth: number; annual: number } {
  if (billing === "annual") {
    const annual = tier.monthly * 10;
    return { perMonth: Math.round(annual / 12), annual };
  }
  return { perMonth: tier.monthly, annual: tier.monthly * 12 };
}

/* ---------------- Mock current plan + usage ---------------- */

export type CurrentPlan = {
  trader: TierId | null;     // null = free / no paid trader plan
  developer: TierId | null;  // null = no studio access
  billing: Billing;
  activeAddOns: string[];
};

const STORAGE_KEY = "bayn.billing.currentPlan";

const defaultPlan: CurrentPlan = {
  trader: null,
  developer: null,
  billing: "annual",
  activeAddOns: [],
};

let mock: CurrentPlan = { ...defaultPlan };

function readStoredPlan(): CurrentPlan {
  if (typeof window === "undefined") return mock;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return mock;
    const stored = JSON.parse(raw) as Partial<CurrentPlan>;
    mock = { ...defaultPlan, ...stored, activeAddOns: stored.activeAddOns ?? [] };
  } catch { /* noop */ }
  return mock;
}

function persistPlan() {
  if (typeof window === "undefined") return;
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(mock)); } catch { /* noop */ }
  window.dispatchEvent(new CustomEvent("bayn-debug-event"));
}

export function getCurrentPlan(): CurrentPlan { return readStoredPlan(); }
export function setCurrentPlan(next: Partial<CurrentPlan>) {
  const before = { ...readStoredPlan(), activeAddOns: [...mock.activeAddOns] };
  mock = { ...mock, ...next, activeAddOns: next.activeAddOns ?? mock.activeAddOns };
  persistPlan();
  logDebugEvent({
    type: "subscription",
    message: `Plan updated: trader ${before.trader ?? "free"} → ${mock.trader ?? "free"}, studio ${before.developer ?? "none"} → ${mock.developer ?? "none"}`,
    meta: { before, after: mock },
  });
}

export function resetCurrentPlan() {
  const before = { ...readStoredPlan(), activeAddOns: [...mock.activeAddOns] };
  mock = { ...defaultPlan };
  persistPlan();
  logDebugEvent({ type: "reset", message: "Billing plan reset to free / no Studio", meta: { before, after: mock } });
}

/* ---------------- Slot system (mock) ---------------- */
/**
 * Free strategies (one per asset class) never count against the slot quota.
 * Every other premium catalog strategy consumes one slot from the user's
 * tier allotment + any add-on slots they've purchased.
 */
export const FREE_STRATEGY_IDS = new Set<string>([
  "s-meanrev-spy", "s-btc-hourly-mr", "s-spy-otm-put", "s-mes-orb",
]);

export function isFreeStrategy(id: string) { return FREE_STRATEGY_IDS.has(id); }

/** Count how many add-on slots the user has purchased. */
export function getAddOnSlotCount(): number {
  let n = 0;
  for (const a of readStoredPlan().activeAddOns) {
    if (a === "trader-extra-strategy") n += 1;
    if (a === "trader-strategy-pack-5") n += 5;
  }
  return n;
}

/** Total premium slots = tier allotment + add-ons. -1 = unlimited. */
export function getTotalSlots(): number {
  const plan = readStoredPlan();
  const tier = plan.trader ? getTier(plan.trader) : null;
  const base = tier?.includedSlots ?? 0;
  if (base === -1) return -1;
  return base + getAddOnSlotCount();
}

export type SlotCheck =
  | { ok: true; reason: "free" | "available"; used: number; total: number }
  | { ok: false; reason: "no-plan" | "slot-limit"; used: number; total: number };

/**
 * Decide whether a user can follow this strategy right now.
 * `followedNonFreeIds` is the set of currently-followed premium strategy ids.
 */
export function checkSlotAvailability(strategyId: string, followedNonFreeIds: string[]): SlotCheck {
  if (isFreeStrategy(strategyId)) {
    return { ok: true, reason: "free", used: followedNonFreeIds.length, total: getTotalSlots() };
  }
  const total = getTotalSlots();
  const used = followedNonFreeIds.length;
  if (total === -1) return { ok: true, reason: "available", used, total };
  if (total === 0) return { ok: false, reason: "no-plan", used, total };
  if (used >= total) return { ok: false, reason: "slot-limit", used, total };
  return { ok: true, reason: "available", used, total };
}

/** Mock purchase: append an add-on id to active list. */
export function purchaseAddOn(addOnId: "trader-extra-strategy" | "trader-strategy-pack-5") {
  readStoredPlan();
  if (!mock.activeAddOns.includes(addOnId)) {
    setCurrentPlan({ activeAddOns: [...mock.activeAddOns, addOnId] });
    logDebugEvent({ type: "subscription", message: `Add-on purchased: ${addOnId}` });
  }
}

/** Mock upgrade: set the trader tier directly. */
export function upgradePlan(tier: TierId) {
  if (tier.startsWith("studio")) setCurrentPlan({ developer: tier });
  else setCurrentPlan({ trader: tier });
}

export type UsageKey = "trader-slots" | "studio-strategies" | "studio-backtests" | "studio-live" | "trader-ai";
export type Usage = { key: UsageKey; label: string; current: number; limit: number; period?: string };

export function getUsage(followedNonFreeCount = 0): Usage[] {
  const plan = readStoredPlan();
  const trader = plan.trader ? getTier(plan.trader) : null;
  const studio = plan.developer ? getTier(plan.developer) : null;
  return [
    { key: "trader-slots", label: "Premium strategy slots",
      current: followedNonFreeCount, limit: getTotalSlots() },
    { key: "trader-ai", label: "Trader-mode AI queries",
      current: 0, limit: trader?.id === "trader-signal" ? 50 : trader ? -1 : 0, period: "this month" },
    { key: "studio-strategies", label: "Active strategies",
      current: 0, limit: studio?.includedSlots ?? 0 },
    { key: "studio-backtests", label: "Backtest runs",
      current: 0, limit: studio?.meta?.backtestRuns ?? 0, period: "this month" },
    { key: "studio-live", label: "Live forward-tests",
      current: 0, limit: studio?.meta?.liveStrategies ?? 0 },
  ];
}

export function formatLimit(n: number): string {
  return n === -1 ? "Unlimited" : String(n);
}
