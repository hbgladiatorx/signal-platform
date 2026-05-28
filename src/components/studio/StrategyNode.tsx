import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { cn } from "@/lib/utils";
import type { NodeCategory } from "@/lib/types";
import { Database, LineChart as IndIcon, GitMerge, ShieldAlert, Zap } from "lucide-react";

const CATEGORY_STYLE: Record<
  NodeCategory,
  { ring: string; text: string; bg: string; label: string; icon: any; handleBg: string; hint: string }
> = {
  data:      { ring: "ring-stocks/50",  text: "text-stocks",  bg: "bg-stocks/10",  label: "1 · DATA",      icon: Database,    handleBg: "!bg-stocks",  hint: "Start here — feeds market data forward" },
  indicator: { ring: "ring-futures/50", text: "text-futures", bg: "bg-futures/10", label: "2 · INDICATOR", icon: IndIcon,     handleBg: "!bg-futures", hint: "Transforms data into a number" },
  logic:     { ring: "ring-gold/50",    text: "text-gold",    bg: "bg-gold/10",    label: "3 · LOGIC",     icon: GitMerge,    handleBg: "!bg-gold",    hint: "Combines values into true/false" },
  risk:      { ring: "ring-crypto/50",  text: "text-crypto",  bg: "bg-crypto/10",  label: "4 · RISK",      icon: ShieldAlert, handleBg: "!bg-crypto",  hint: "Sets stop, target, position size" },
  signal:    { ring: "ring-violet/70",  text: "text-violet",  bg: "bg-violet/15",  label: "5 · SIGNAL",    icon: Zap,         handleBg: "!bg-violet",  hint: "Final step — fires the trade" },
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

  const handleCls =
    "!size-3 !border-2 !border-background transition-transform hover:!scale-150 " + s.handleBg;

  return (
    <div
      className={cn(
        "group relative min-w-[200px] rounded-lg border border-border bg-elevated shadow-md transition",
        "ring-1",
        s.ring,
        selected && "ring-2 ring-offset-2 ring-offset-background ring-violet",
      )}
    >
      {/* Input handle (left) */}
      {!isSource && (
        <>
          <Handle type="target" position={Position.Left} id="in" className={handleCls} />
          <span className="pointer-events-none absolute -left-[58px] top-1/2 -translate-y-1/2 rounded bg-background/80 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground opacity-0 transition group-hover:opacity-100">
            input
          </span>
        </>
      )}

      <div className={cn("flex items-center gap-2 rounded-t-lg border-b border-border px-3 py-1.5", s.bg)}>
        <Icon className={cn("size-3.5", s.text)} />
        <span className={cn("font-mono text-[10px] uppercase tracking-wider", s.text)}>{s.label}</span>
      </div>
      <div className="px-3 py-2">
        <div className="text-sm font-medium">{data.label}</div>
        {summary ? (
          <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">{summary}</div>
        ) : (
          <div className="mt-0.5 truncate text-[10px] italic text-muted-foreground">{s.hint}</div>
        )}
      </div>

      {/* Output handle (right) */}
      {!isTerminal && (
        <>
          <Handle type="source" position={Position.Right} id="out" className={handleCls} />
          <span className="pointer-events-none absolute -right-[68px] top-1/2 -translate-y-1/2 rounded bg-background/80 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground opacity-0 transition group-hover:opacity-100">
            drag →
          </span>
        </>
      )}
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
