// Debug logger — panel removed; kept as no-op so existing call sites compile.
export type DebugEvent = {
  type: "onboarding" | "subscription" | "follow" | "reset" | string;
  message: string;
  meta?: unknown;
};
export function logDebugEvent(_event: DebugEvent): void { /* no-op */ }
export function getDebugEvents(): DebugEvent[] { return []; }
export function clearDebugEvents(): void { /* no-op */ }
