import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Node } from "reactflow";
import type { StrategyNodeData } from "./StrategyNode";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface FieldDef { key: string; label: string; type: "text" | "number" | "select"; options?: string[]; }

const FIELDS: Record<string, FieldDef[]> = {
  price: [
    { key: "symbol", label: "Symbol", type: "text" },
    { key: "timeframe", label: "Timeframe", type: "select", options: ["1m","5m","15m","1h","4h","1d"] },
  ],
  sma: [{ key: "period", label: "Period", type: "number" }, { key: "source", label: "Source", type: "select", options: ["close","open","high","low","hl2","hlc3"] }],
  ema: [{ key: "period", label: "Period", type: "number" }, { key: "source", label: "Source", type: "select", options: ["close","open","high","low"] }],
  vwap: [{ key: "period", label: "Period", type: "number" }],
  rsi: [{ key: "period", label: "Period", type: "number" }],
  macd: [{ key: "fast", label: "Fast", type: "number" }, { key: "slow", label: "Slow", type: "number" }, { key: "signal", label: "Signal", type: "number" }],
  bb: [{ key: "period", label: "Period", type: "number" }, { key: "stdDev", label: "Std Dev", type: "number" }],
  atr: [{ key: "period", label: "Period", type: "number" }],
  stoch: [{ key: "k", label: "%K", type: "number" }, { key: "d", label: "%D", type: "number" }],
  formula: [{ key: "expr", label: "Expression", type: "text" }],

  comparator: [
    { key: "op", label: "Operator", type: "select", options: [">","<","=",">=","<="] },
    { key: "value", label: "Value", type: "number" },
  ],
  crossover: [{ key: "op", label: "Type", type: "select", options: ["crosses_above","crosses_below"] }],
  timeWindow: [{ key: "start", label: "Start", type: "text" }, { key: "end", label: "End", type: "text" }],
  cooldown: [{ key: "bars", label: "Bars", type: "number" }],

  positionSize: [
    { key: "type", label: "Type", type: "select", options: ["percent_account","fixed_dollar","atr_based"] },
    { key: "value", label: "Value", type: "number" },
  ],
  stopLoss: [
    { key: "type", label: "Type", type: "select", options: ["percent","atr","trailing","structure"] },
    { key: "value", label: "Value", type: "number" },
    { key: "atrPeriod", label: "ATR Period", type: "number" },
    { key: "multiple", label: "Multiple", type: "number" },
  ],
  takeProfit: [
    { key: "type", label: "Type", type: "select", options: ["percent","r_multiple","indicator"] },
    { key: "value", label: "Value", type: "number" },
  ],
  maxDailyLoss: [{ key: "value", label: "% of Equity", type: "number" }],
  maxConcurrent: [{ key: "value", label: "Max", type: "number" }],

  entry: [{ key: "direction", label: "Direction", type: "select", options: ["LONG","SHORT"] }],
  exit: [],
  alert: [{ key: "message", label: "Message", type: "text" }],

  and: [], or: [], not: [], volume: [], orderBook: [{ key: "depth", label: "Depth", type: "number" }],
  optionsChain: [{ key: "symbol", label: "Symbol", type: "text" }], fundamentals: [], econCalendar: [],
};

export function NodeInspector({
  node, onChange, onDelete,
}: {
  node: Node<StrategyNodeData> | null;
  onChange: (id: string, config: Record<string, unknown>) => void;
  onDelete: (id: string) => void;
}) {
  if (!node) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        <p>Select a node to edit its properties.</p>
      </div>
    );
  }
  const fields = FIELDS[node.data.nodeType] ?? [];
  const config = (node.data.config ?? {}) as Record<string, unknown>;

  const setField = (key: string, val: unknown) => onChange(node.id, { ...config, [key]: val });

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border p-3">
        <div>
          <div className="text-xs font-mono uppercase tracking-wider text-violet">{node.data.category}</div>
          <div className="font-medium">{node.data.label}</div>
        </div>
        <Button size="icon" variant="ghost" onClick={() => onDelete(node.id)}>
          <Trash2 className="size-4 text-danger" />
        </Button>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {fields.length === 0 && <p className="text-xs text-muted-foreground">This node has no editable properties.</p>}
        {fields.map((f) => (
          <div key={f.key} className="space-y-1">
            <Label className="text-xs">{f.label}</Label>
            {f.type === "select" ? (
              <Select value={String(config[f.key] ?? "")} onValueChange={(v) => setField(f.key, v)}>
                <SelectTrigger className="h-9 bg-background"><SelectValue placeholder={`Select ${f.label}`} /></SelectTrigger>
                <SelectContent>
                  {f.options!.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                </SelectContent>
              </Select>
            ) : (
              <Input
                type={f.type}
                value={String(config[f.key] ?? "")}
                onChange={(e) => setField(f.key, f.type === "number" ? Number(e.target.value) : e.target.value)}
                className="h-9 bg-background"
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
