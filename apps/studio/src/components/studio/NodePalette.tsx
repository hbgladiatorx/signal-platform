import { cn } from "@/lib/utils";
import { Database, LineChart, GitMerge, ShieldAlert, Zap } from "lucide-react";
import type { NodeCategory } from "@/lib/types";

export interface PaletteNode {
  type: string;
  label: string;
  category: NodeCategory;
  defaultData: Record<string, unknown>;
  assetClassOnly?: string[];
}

export const PALETTE: PaletteNode[] = [
  // Data
  { type: "price", label: "Price (OHLCV)", category: "data", defaultData: { symbol: "BTC-PERP", timeframe: "1h" } },
  { type: "volume", label: "Volume", category: "data", defaultData: {} },
  { type: "orderBook", label: "Order Book", category: "data", defaultData: { depth: 10 }, assetClassOnly: ["crypto"] },
  { type: "optionsChain", label: "Options Chain", category: "data", defaultData: { symbol: "SPY" }, assetClassOnly: ["options"] },
  { type: "fundamentals", label: "Fundamentals", category: "data", defaultData: {}, assetClassOnly: ["stocks"] },
  { type: "econCalendar", label: "Economic Calendar", category: "data", defaultData: {} },

  // Indicators
  { type: "sma", label: "SMA", category: "indicator", defaultData: { period: 20, source: "close" } },
  { type: "ema", label: "EMA", category: "indicator", defaultData: { period: 20, source: "close" } },
  { type: "vwap", label: "VWAP", category: "indicator", defaultData: { period: 50 } },
  { type: "rsi", label: "RSI", category: "indicator", defaultData: { period: 14 } },
  { type: "macd", label: "MACD", category: "indicator", defaultData: { fast: 12, slow: 26, signal: 9 } },
  { type: "bb", label: "Bollinger Bands", category: "indicator", defaultData: { period: 20, stdDev: 2 } },
  { type: "atr", label: "ATR", category: "indicator", defaultData: { period: 14 } },
  { type: "stoch", label: "Stochastic", category: "indicator", defaultData: { k: 14, d: 3 } },
  { type: "formula", label: "Custom Formula", category: "indicator", defaultData: { expr: "close > open" } },

  // Logic
  { type: "comparator", label: "Comparator", category: "logic", defaultData: { op: ">", value: 0 } },
  { type: "crossover", label: "Crossover", category: "logic", defaultData: { op: "crosses_above" } },
  { type: "and", label: "AND", category: "logic", defaultData: {} },
  { type: "or", label: "OR", category: "logic", defaultData: {} },
  { type: "not", label: "NOT", category: "logic", defaultData: {} },
  { type: "timeWindow", label: "Time Window", category: "logic", defaultData: { start: "09:30", end: "15:45" } },
  { type: "cooldown", label: "Cooldown", category: "logic", defaultData: { bars: 6 } },

  // Risk
  { type: "positionSize", label: "Position Size", category: "risk", defaultData: { type: "percent_account", value: 2 } },
  { type: "stopLoss", label: "Stop Loss", category: "risk", defaultData: { type: "percent", value: 1.5 } },
  { type: "takeProfit", label: "Take Profit", category: "risk", defaultData: { type: "r_multiple", value: 2 } },
  { type: "maxDailyLoss", label: "Max Daily Loss", category: "risk", defaultData: { value: 3 } },
  { type: "maxConcurrent", label: "Max Concurrent Positions", category: "risk", defaultData: { value: 3 } },

  // Signal
  { type: "entry", label: "Entry Signal", category: "signal", defaultData: { direction: "LONG" } },
  { type: "exit", label: "Exit Signal", category: "signal", defaultData: {} },
  { type: "alert", label: "Alert Only", category: "signal", defaultData: { message: "" } },
];

const CATEGORY_META: Record<NodeCategory, { label: string; icon: any; text: string }> = {
  data:      { label: "Data Sources",   icon: Database,    text: "text-stocks" },
  indicator: { label: "Indicators",     icon: LineChart,   text: "text-futures" },
  logic:     { label: "Logic",          icon: GitMerge,    text: "text-gold" },
  risk:      { label: "Risk Management", icon: ShieldAlert, text: "text-crypto" },
  signal:    { label: "Signal Output",  icon: Zap,         text: "text-violet" },
};

export function NodePalette({ onAdd }: { onAdd: (p: PaletteNode) => void }) {
  const cats: NodeCategory[] = ["data", "indicator", "logic", "risk", "signal"];
  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-3">
      <div>
        <h3 className="text-sm font-semibold">Node Palette</h3>
        <p className="text-xs text-muted-foreground">Click to add to canvas</p>
      </div>
      {cats.map((c) => {
        const meta = CATEGORY_META[c];
        const Icon = meta.icon;
        const items = PALETTE.filter((p) => p.category === c);
        return (
          <div key={c}>
            <div className={cn("mb-2 flex items-center gap-2 text-xs font-mono uppercase tracking-wider", meta.text)}>
              <Icon className="size-3.5" /> {meta.label}
            </div>
            <div className="flex flex-col gap-1">
              {items.map((p) => (
                <button key={p.type} onClick={() => onAdd(p)}
                  className="flex items-center justify-between rounded-md border border-border bg-elevated px-2.5 py-1.5 text-left text-xs transition-colors hover:border-violet/40 hover:bg-violet/5">
                  <span>{p.label}</span>
                  <span className="font-mono text-[9px] text-muted-foreground">+</span>
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
