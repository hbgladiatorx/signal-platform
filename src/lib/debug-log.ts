export type DebugEvent = {
  id: string;
  at: string;
  type: "onboarding" | "subscription" | "reset" | "follow" | "system";
  message: string;
  meta?: Record<string, unknown>;
};

const DEBUG_KEY = "bayn.debug.events";
const MAX_EVENTS = 80;

function readEvents(): DebugEvent[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(DEBUG_KEY) ?? "[]") as DebugEvent[];
  } catch {
    return [];
  }
}

export function getDebugEvents() {
  return readEvents();
}

export function logDebugEvent(event: Omit<DebugEvent, "id" | "at">) {
  if (typeof window === "undefined") return;
  const next: DebugEvent = {
    ...event,
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    at: new Date().toISOString(),
  };
  try {
    window.localStorage.setItem(DEBUG_KEY, JSON.stringify([next, ...readEvents()].slice(0, MAX_EVENTS)));
  } catch { /* noop */ }
  window.dispatchEvent(new CustomEvent("bayn-debug-event", { detail: next }));
}

export function clearDebugEvents() {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(DEBUG_KEY); } catch { /* noop */ }
  window.dispatchEvent(new CustomEvent("bayn-debug-event"));
}