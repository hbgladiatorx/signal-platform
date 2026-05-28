import { useCallback, useEffect, useState } from "react";

/**
 * Lightweight localStorage-backed user prefs. Single source of truth for:
 *  - Watchlist tickers (top market ticker carousel + market overview)
 *  - News categories (which sectors show in the news wire)
 *  - Followed strategy ids (overlay added to the default followed list)
 *
 * Each pref is its own hook so subscribers re-render only when their slice changes.
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
    } catch {
      /* quota / SSR — ignore */
    }
  }
  notify(key);
}

function usePref<T>(key: string, fallback: T) {
  const [value, setValue] = useState<T>(() => read<T>(key, fallback));

  useEffect(() => {
    const l: Listener = () => setValue(read<T>(key, fallback));
    let set = listeners.get(key);
    if (!set) {
      set = new Set();
      listeners.set(key, set);
    }
    set.add(l);
    // Sync on mount in case another tab/window updated.
    l();
    return () => {
      set!.delete(l);
    };
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

/* ---------------- Watchlist ---------------- */
export const DEFAULT_WATCHLIST = [
  "SPY", "QQQ", "AAPL", "NVDA", "BTC", "ETH", "ES", "CL", "VIX",
];

export function useWatchlist() {
  return usePref<string[]>("watchlist", DEFAULT_WATCHLIST);
}

/* ---------------- News categories ---------------- */
export const ALL_NEWS_CATEGORIES = [
  "Markets", "Crypto", "Macro", "Earnings", "Energy", "Rates",
] as const;
export type NewsCategory = (typeof ALL_NEWS_CATEGORIES)[number];

export function useNewsCategories() {
  return usePref<NewsCategory[]>("news.categories", [...ALL_NEWS_CATEGORIES]);
}

/* ---------------- Followed strategy ids (overlay) ---------------- */
export function useFollowedOverlay() {
  return usePref<{ added: string[]; removed: string[] }>("follows", { added: [], removed: [] });
}

/** Imperative read (for API layer). */
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
}

/* ---------------- Account seeding / onboarding flags ----------------
 * New accounts start completely blank. The onboarding flow flips these
 * once the user picks their path and activates their free strategies.
 */
export function getTraderSeeded() { return read<boolean>("traderSeeded", false); }
export function setTraderSeeded(v: boolean) { write("traderSeeded", v); }
export function useTraderSeeded() { return usePref<boolean>("traderSeeded", false); }

export function getStudioSeeded() { return read<boolean>("studioSeeded", false); }
export function setStudioSeeded(v: boolean) { write("studioSeeded", v); }
export function useStudioSeeded() { return usePref<boolean>("studioSeeded", false); }

export function getOnboarded() { return read<boolean>("onboarded", false); }
export function setOnboarded(v: boolean) { write("onboarded", v); }
export function useOnboarded() { return usePref<boolean>("onboarded", false); }

/** Wipe local prefs — used on sign-out so a different account starts blank. */
export function resetAllPrefs() {
  const keys = ["watchlist", "news.categories", "follows", "traderSeeded", "studioSeeded", "onboarded"];
  for (const k of keys) {
    inMemory.delete(k);
    if (typeof window !== "undefined") {
      try { window.localStorage.removeItem(STORAGE_PREFIX + k); } catch { /* noop */ }
    }
    notify(k);
  }
}

