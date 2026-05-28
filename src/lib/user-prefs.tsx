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

type Listener = () => void;
const listeners = new Map<string, Set<Listener>>();
const inMemory = new Map<string, unknown>();

function notify(key: string) {
  listeners.get(key)?.forEach((l) => l());
}

function read<T>(key: string, fallback: T): T {
  if (inMemory.has(key)) return inMemory.get(key) as T;
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + key);
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
      window.localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
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
  return usePref<AssetClass[]>("assetClasses", [...ALL_ASSET_CLASSES]);
}
export function getEnabledAssetClasses() {
  return read<AssetClass[]>("assetClasses", [...ALL_ASSET_CLASSES]);
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
export function useAccountSize() { return usePref<number>("trading.accountSize", 25000); }
export function useRiskPerTrade() { return usePref<number>("trading.riskPerTrade", 0.01); }
export function useDefaultTimeframe() { return usePref<string>("trading.timeframe", "1H"); }
export function useDefaultChartType() { return usePref<string>("trading.chartType", "candle"); }
export function getAccountSize() { return read<number>("trading.accountSize", 25000); }

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

/** Wipe local prefs — used on sign-out so the next account starts blank. */
export function resetAllPrefs() {
  const keys = [
    "watchlist", "news.categories", "news.sources", "news.onlyWatched",
    "follows", "assetClasses", "liveTracking", "home.layout", "home.hidden",
    "trading.accountSize", "trading.riskPerTrade", "trading.timeframe",
    "trading.chartType", "notifications",
    "traderSeeded", "studioSeeded", "onboarded",
  ];
  for (const k of keys) {
    inMemory.delete(k);
    if (typeof window !== "undefined") {
      try { window.localStorage.removeItem(STORAGE_PREFIX + k); } catch { /* noop */ }
    }
    notify(k);
  }
  logDebugEvent({ type: "reset", message: "All onboarding and preference state reset" });
}
