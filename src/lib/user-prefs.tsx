import { useCallback, useEffect, useState } from "react";
import type { AssetClass } from "./types";
import { logDebugEvent } from "./debug-log";

/**
 * Single source of truth for trader-side personalization.
 * Empty by default. Populated by user choice (onboarding + /app/customize).
 *
 * Mock-now, Supabase-ready: each pref is its own keyed slice with imperative
 * read/write + a subscribing hook so any consumer re-renders on change.
 */

const STORAGE_PREFIX = "bayn.prefs.";
let storageScope = "anon";

type Listener = () => void;
const listeners = new Map<string, Set<Listener>>();
const inMemory = new Map<string, unknown>();

function notify(key: string) {
  listeners.get(key)?.forEach((l) => l());
}

function storageKey(key: string) {
  return `${STORAGE_PREFIX}${storageScope}.${key}`;
}

export function setPreferenceScope(userId: string | null) {
  const next = userId ?? "anon";
  if (next === storageScope) return;
  storageScope = next;
  inMemory.clear();
  listeners.forEach((set) => set.forEach((l) => l()));
}

function read<T>(key: string, fallback: T): T {
  if (inMemory.has(key)) return inMemory.get(key) as T;
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(storageKey(key));
    if (raw == null) return fallback;
    const parsed = JSON.parse(raw) as T;
    inMemory.set(key, parsed);
    return parsed;
  } catch {
    return fallback;
  }
}

function write<T>(key: string, value: T) {
  inMemory.set(key, value);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(storageKey(key), JSON.stringify(value));
    } catch { /* quota / SSR */ }
  }
  notify(key);
}

function usePref<T>(key: string, fallback: T) {
  const [value, setValue] = useState<T>(() => read<T>(key, fallback));
  useEffect(() => {
    const l: Listener = () => setValue(read<T>(key, fallback));
    let set = listeners.get(key);
    if (!set) { set = new Set(); listeners.set(key, set); }
    set.add(l);
    l();
    return () => { set!.delete(l); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const setter = useCallback(
    (next: T | ((prev: T) => T)) => {
      const cur = read<T>(key, fallback);
      const v = typeof next === "function" ? (next as (p: T) => T)(cur) : next;
      write(key, v);
    },
    [key, fallback],
  );
  return [value, setter] as const;
}

/* ---------------- Watchlist (empty by default) ---------------- */
// Kept for backwards compatibility — new accounts start blank.
export const DEFAULT_WATCHLIST: string[] = [];
export function useWatchlist() { return usePref<string[]>("watchlist", []); }
export function getWatchlist() { return read<string[]>("watchlist", []); }
export function setWatchlist(v: string[]) { write("watchlist", v); }

/* ---------------- News categories ---------------- */
export const ALL_NEWS_CATEGORIES = [
  "Markets", "Crypto", "Macro", "Earnings", "Energy", "Rates",
] as const;
export type NewsCategory = (typeof ALL_NEWS_CATEGORIES)[number];
// Empty by default.
export function useNewsCategories() { return usePref<NewsCategory[]>("news.categories", []); }

/* ---------------- News sources ---------------- */
export type NewsSource = {
  id: string; name: string; enabled: boolean; premium?: boolean;
};
export const ALL_NEWS_SOURCES: NewsSource[] = [
  { id: "reuters", name: "Reuters", enabled: false },
  { id: "wsj", name: "WSJ", enabled: false, premium: true },
  { id: "bloomberg", name: "Bloomberg", enabled: false, premium: true },
  { id: "marketwatch", name: "MarketWatch", enabled: false },
  { id: "benzinga", name: "Benzinga", enabled: false },
  { id: "coindesk", name: "CoinDesk", enabled: false },
  { id: "theblock", name: "The Block", enabled: false },
  { id: "acro", name: "ACRO", enabled: false },
];
export function useNewsSources() {
  return usePref<NewsSource[]>("news.sources", ALL_NEWS_SOURCES);
}
export function useOnlyNewsForWatched() {
  return usePref<boolean>("news.onlyWatched", false);
}

/* ---------------- Followed strategy ids (overlay) ---------------- */
export function useFollowedOverlay() {
  return usePref<{ added: string[]; removed: string[] }>("follows", { added: [], removed: [] });
}
export function readFollowedOverlay() {
  return read<{ added: string[]; removed: string[] }>("follows", { added: [], removed: [] });
}
export function toggleFollow(id: string, follow: boolean) {
  const cur = readFollowedOverlay();
  const added = new Set(cur.added);
  const removed = new Set(cur.removed);
  if (follow) { added.add(id); removed.delete(id); }
  else { removed.add(id); added.delete(id); }
  write("follows", { added: [...added], removed: [...removed] });
  logDebugEvent({ type: "follow", message: `${follow ? "Followed" : "Unfollowed"} strategy ${id}`, meta: { id, follow } });
}

/* ---------------- Enabled asset classes (master cascade) ---------------- */
export const ALL_ASSET_CLASSES: AssetClass[] = ["stocks", "crypto", "options", "futures"];
export function useEnabledAssetClasses() {
  return usePref<AssetClass[]>("assetClasses", []);
}
export function getEnabledAssetClasses() {
  return read<AssetClass[]>("assetClasses", []);
}
export function setEnabledAssetClasses(v: AssetClass[]) { write("assetClasses", v); }

/* ---------------- Live tracking strategy ---------------- */
export function useLiveTrackingStrategy() {
  return usePref<string | null>("liveTracking", null);
}
export function getLiveTrackingStrategy() { return read<string | null>("liveTracking", null); }
export function setLiveTrackingStrategy(id: string | null) { write("liveTracking", id); }

/* ---------------- Home layout ---------------- */
export type HomeSection =
  | "liveTracking" | "marketOverview" | "myStrategies"
  | "recentSignals" | "marketWire" | "performance";
export const DEFAULT_HOME_LAYOUT: HomeSection[] = [
  "liveTracking", "marketOverview", "myStrategies",
  "recentSignals", "marketWire", "performance",
];
export function useHomeLayout() {
  return usePref<HomeSection[]>("home.layout", DEFAULT_HOME_LAYOUT);
}
export function useHiddenSections() {
  return usePref<HomeSection[]>("home.hidden", []);
}

/* ---------------- Trading defaults ---------------- */
export function useAccountSize() { return usePref<number>("trading.accountSize", 0); }
export function useRiskPerTrade() { return usePref<number>("trading.riskPerTrade", 0); }
export function useDefaultTimeframe() { return usePref<string>("trading.timeframe", "1H"); }
export function useDefaultChartType() { return usePref<string>("trading.chartType", "candle"); }
export function getAccountSize() { return read<number>("trading.accountSize", 0); }
export function setAccountSize(v: number) { write("trading.accountSize", v); }
export function setRiskPerTrade(v: number) { write("trading.riskPerTrade", v); }

/* ---------------- Notifications ---------------- */
export type NotifKey =
  | "signalFired" | "signalHitTarget" | "signalHitStop"
  | "weeklySummary" | "strategyHWM" | "tickerNews";
export type NotificationPrefs = Record<NotifKey, boolean>;
const DEFAULT_NOTIFS: NotificationPrefs = {
  signalFired: true, signalHitTarget: true, signalHitStop: true,
  weeklySummary: true, strategyHWM: false, tickerNews: false,
};
export function useNotifications() {
  return usePref<NotificationPrefs>("notifications", DEFAULT_NOTIFS);
}

/* ---------------- Account seeding / onboarding flags ---------------- */
export function getTraderSeeded() { return read<boolean>("traderSeeded", false); }
export function setTraderSeeded(v: boolean) { write("traderSeeded", v); logDebugEvent({ type: "onboarding", message: `Trader onboarding seeded: ${v}` }); }
export function useTraderSeeded() { return usePref<boolean>("traderSeeded", false); }

export function getStudioSeeded() { return read<boolean>("studioSeeded", false); }
export function setStudioSeeded(v: boolean) { write("studioSeeded", v); logDebugEvent({ type: "onboarding", message: `Studio onboarding seeded: ${v}` }); }
export function useStudioSeeded() { return usePref<boolean>("studioSeeded", false); }

export function getOnboarded() { return read<boolean>("onboarded", false); }
export function setOnboarded(v: boolean) { write("onboarded", v); logDebugEvent({ type: "onboarding", message: `Onboarding flag set: ${v}` }); }
export function useOnboarded() { return usePref<boolean>("onboarded", false); }

export type OnboardingPath = "trader" | "developer" | "both";
export function getOnboardingPath() { return read<OnboardingPath | null>("onboarding.path", null); }
export function setOnboardingPath(v: OnboardingPath) { write("onboarding.path", v); logDebugEvent({ type: "onboarding", message: `Onboarding path selected: ${v}` }); }
export function useOnboardingPath() { return usePref<OnboardingPath | null>("onboarding.path", null); }


/* ---------------- Identity ---------------- */
export type Identity = {
  displayName: string;
  timezone: string;
  currency: string;
  avatarUrl: string | null;
};
const DEFAULT_IDENTITY: Identity = { displayName: "", timezone: "", currency: "USD", avatarUrl: null };
export function useIdentity() { return usePref<Identity>("identity", DEFAULT_IDENTITY); }
export function setIdentity(v: Identity) { write("identity", v); }

/* ---------------- Experience profile ---------------- */
export type ExperienceLevel = "retail" | "active" | "professional" | "institutional";
export type ExperienceProfile = {
  level: ExperienceLevel | null;
  years: string | null; // bucket: "<1", "1-3", "3-5", "5-10", "10+"
  motivations: string[];
  signalSources: string[];
};
const DEFAULT_EXP: ExperienceProfile = { level: null, years: null, motivations: [], signalSources: [] };
export function useExperienceProfile() { return usePref<ExperienceProfile>("experience", DEFAULT_EXP); }

/* ---------------- Risk + trading defaults (extended) ---------------- */
export function useMaxConcurrentPositions() { return usePref<number>("trading.maxConcurrent", 5); }
export function useDailyLossLimit() {
  return usePref<{ enabled: boolean; threshold: number }>("trading.dailyLossLimit", { enabled: false, threshold: 0 });
}

/* ---------------- Broker connections (preference only) ---------------- */
export type BrokerId = "coinbase" | "ibkr" | "tradier" | "topstepx" | "robinhood-agentic";
export function useBrokerConnections() { return usePref<BrokerId[]>("brokers.connections", []); }
export function useDefaultBrokerByAssetClass() {
  return usePref<Partial<Record<AssetClass, BrokerId>>>("brokers.defaultByAssetClass", {});
}

/* ---------------- AI agent setup ---------------- */
export type AgentPlatform = "claude-code" | "claude-desktop" | "chatgpt" | "codex" | "cursor" | "other";
export function useAgentSetup() {
  return usePref<{
    platform: AgentPlatform | null;
    baynMcpConnected: boolean;
    brokerageAgentConnected: boolean;
    readSignalFeed: boolean;
  }>("agent.setup", { platform: null, baynMcpConnected: false, brokerageAgentConnected: false, readSignalFeed: false });
}

/* ---------------- Studio preferences ---------------- */
export type BuilderEntry = "template" | "blank" | "ai-describe";
export type StudioExperience = "none" | "some" | "strong" | "professional";
export type NodeStyle = "conservative" | "minimal" | "aggressive";

export function useStudioAssetClasses() { return usePref<AssetClass[]>("studio.assetClasses", []); }
export function useStudioExperience() {
  return usePref<{ level: StudioExperience | null; usedNodeBuilder: boolean | null; entry: BuilderEntry | null }>(
    "studio.experience", { level: null, usedNodeBuilder: null, entry: null },
  );
}
export function useBacktestDefaults() {
  return usePref<{
    startingCapital: number;
    dateRange: "1Y" | "3Y" | "5Y" | "MAX";
    commissionModel: "per-share" | "per-contract" | "percent" | "custom";
    commissionValue: number;
    slippageBps: number;
    currency: string;
  }>("studio.backtestDefaults", {
    startingCapital: 0, dateRange: "3Y", commissionModel: "per-share",
    commissionValue: 0, slippageBps: 0, currency: "USD",
  });
}
export function useForwardTestDefaults() {
  return usePref<{
    paperCapital: number;
    autoPromoteDays: number;
    delivery: { inApp: boolean; email: boolean; push: boolean };
  }>("studio.forwardTestDefaults", {
    paperCapital: 0, autoPromoteDays: 30, delivery: { inApp: true, email: false, push: false },
  });
}
export function useStudioAiPreferences() {
  return usePref<{ nodeStyle: NodeStyle; rememberSession: boolean }>(
    "studio.aiPrefs", { nodeStyle: "minimal", rememberSession: true },
  );
}
export function useStudioWorkspaceDefaults() {
  return usePref<{ view: "grid" | "list" | "kanban"; defaultAssetClass: AssetClass | null }>(
    "studio.workspaceDefaults", { view: "grid", defaultAssetClass: null },
  );
}
export function usePayoutPreference() {
  return usePref<{ method: "ach" | "wire" | "stripe" | null }>("studio.payout", { method: null });
}

/* ---------------- Default mode on login (both-mode users) ---------------- */
export function useDefaultModeOnLogin() {
  return usePref<"trader" | "studio" | null>("defaultModeOnLogin", null);
}

/* ---------------- Resume support ---------------- */
export function useOnboardingResume() {
  return usePref<{ step: number; total: number } | null>("onboarding.resume", null);
}
export function setOnboardingResume(v: { step: number; total: number } | null) {
  write("onboarding.resume", v);
}

/* ---------------- Dismissed checklist items ---------------- */
export function useDismissedChecklistItems() {
  return usePref<string[]>("checklist.dismissed", []);
}



/** Wipe local prefs — used on sign-out so the next account starts blank. */
export function resetAllPrefs() {
  const keys = [
    "watchlist", "news.categories", "news.sources", "news.onlyWatched",
    "follows", "assetClasses", "liveTracking", "home.layout", "home.hidden",
    "trading.accountSize", "trading.riskPerTrade", "trading.timeframe",
    "trading.chartType", "trading.maxConcurrent", "trading.dailyLossLimit",
    "notifications", "identity", "experience",
    "brokers.connections", "brokers.defaultByAssetClass",
    "agent.setup",
    "studio.assetClasses", "studio.experience", "studio.backtestDefaults",
    "studio.forwardTestDefaults", "studio.aiPrefs", "studio.workspaceDefaults",
    "studio.payout",
    "defaultModeOnLogin", "onboarding.resume", "checklist.dismissed",
    "traderSeeded", "studioSeeded", "onboarded", "onboarding.path",
  ];
  for (const k of keys) {
    inMemory.delete(k);
    if (typeof window !== "undefined") {
      try {
        window.localStorage.removeItem(storageKey(k));
        window.localStorage.removeItem(STORAGE_PREFIX + k);
      } catch { /* noop */ }
    }
    notify(k);
  }
  logDebugEvent({ type: "reset", message: "All onboarding and preference state reset" });
}

