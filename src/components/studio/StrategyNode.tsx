import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { cn } from "@/lib/utils";
import type { NodeCategory } from "@/lib/types";
import {
  Database, LineChart as IndIcon, GitMerge, ShieldAlert, Zap,
} from "lucide-react";

const CATEGORY_STYLE: Record<NodeCategory, { ring: string; text: string; bg: string; label: string; icon: any }> = {
  data:      { ring: "ring-stocks/40",  text: "text-stocks",  bg: "bg-stocks/10",  label: "DATA",      icon: Database },
  indicator: { ring: "ring-futures/40", text: "text-futures", bg: "bg-futures/10", label: "INDICATOR", icon: IndIcon },
  logic:     { ring: "ring-gold/40",    text: "text-gold",    bg: "bg-gold/10",    label: "LOGIC",     icon: GitMerge },
  risk:      { ring: "ring-crypto/40",  text: "text-crypto",  bg: "bg-crypto/10",  label: "RISK",      icon: ShieldAlert },
  signal:    { ring: "ring-violet/60",  text: "text-violet",  bg: "bg-violet/15",  label: "SIGNAL",    icon: Zap },
};

export interface StrategyNodeData {
  category: NodeCategory;
  label: string;
  nodeType: string;
  config: Record<string, unknown>;
}

function StrategyNodeImpl({ data, selected }: NodeProps<StrategyNodeData>) {
  const s = CATEGORY_STYLE[data.category];
  const Icon = s.icon;
  const isSource = data.category === "data";
  const isTerminal = data.category === "signal";
  const summary = renderSummary(data);

  return (
    <div className={cn(
      "min-w-[180px] rounded-lg border border-border bg-elevated shadow-md transition",
      "ring-1", s.ring,
      selected && "ring-2 ring-offset-2 ring-offset-background ring-violet",
    )}>
      {!isSource && <Handle type="target" position={Position.Left} id="in" />}
      <div className={cn("flex items-center gap-2 rounded-t-lg px-3 py-1.5 border-b border-border", s.bg)}>
        <Icon className={cn("size-3.5", s.text)} />
        <span className={cn("font-mono text-[10px] uppercase tracking-wider", s.text)}>{s.label}</span>
      </div>
      <div className="px-3 py-2">
        <div className="text-sm font-medium">{data.label}</div>
        {summary && <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">{summary}</div>}
      </div>
      {!isTerminal && <Handle type="source" position={Position.Right} id="out" />}
    </div>
  );
}

function renderSummary(d: StrategyNodeData): string {
  const c = d.config as any;
  switch (d.nodeType) {
    case "price": return `${c.symbol ?? "—"} · ${c.timeframe ?? "1h"}`;
    case "sma": case "ema": case "rsi": return `period ${c.period ?? "—"}`;
    case "bb": return `${c.period ?? 20}, ${c.stdDev ?? 2}σ`;
    case "comparator": return `${c.op ?? "?"} ${c.value ?? ""}`;
    case "crossover": return `${c.op ?? "crosses_above"}`;
    case "timeWindow": return c.dte ? `${c.dte} DTE` : `${c.start ?? "—"}–${c.end ?? "—"}`;
    case "stopLoss": return c.type === "atr" ? `ATR(${c.atrPeriod}) × ${c.multiple}` : `${c.value ?? "—"}%`;
    case "takeProfit": return c.type === "r_multiple" ? `${c.value}R` : `${c.value ?? "—"}%`;
    case "positionSize": return c.type === "percent_account" ? `${c.value}% acct` : `$${c.value}`;
    case "entry": return c.direction ?? "LONG";
    case "and": return "AND";
    case "or": return "OR";
    case "not": return "NOT";
    default: return "";
  }
}

export const StrategyNode = memo(StrategyNodeImpl);
