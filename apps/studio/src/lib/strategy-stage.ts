// Lightweight per-strategy validation-stage tracking, persisted to localStorage.
import type { DeployStage } from "@/lib/api/agent";

const KEY = "bayn.strategy.stage";
const ORDER: DeployStage[] = ["draft", "backtested", "oos", "forward", "deployable", "eligible"];

type StageMap = Record<string, DeployStage>;

function read(): StageMap {
  if (typeof window === "undefined") return {};
  try { return JSON.parse(localStorage.getItem(KEY) || "{}") as StageMap; } catch { return {}; }
}
function write(m: StageMap) {
  if (typeof window === "undefined") return;
  localStorage.setItem(KEY, JSON.stringify(m));
  window.dispatchEvent(new Event("bayn.stage.changed"));
}

export function getStage(strategyId: string): DeployStage {
  return read()[strategyId] ?? "draft";
}

export function setStage(strategyId: string, stage: DeployStage) {
  const m = read();
  m[strategyId] = stage;
  write(m);
}

export function advanceStage(strategyId: string, atLeast: DeployStage) {
  const cur = getStage(strategyId);
  if (ORDER.indexOf(atLeast) > ORDER.indexOf(cur)) setStage(strategyId, atLeast);
}

export function nextStage(stage: DeployStage): DeployStage | null {
  const i = ORDER.indexOf(stage);
  return i >= 0 && i < ORDER.length - 1 ? ORDER[i + 1] : null;
}

export { ORDER as STAGE_ORDER };
