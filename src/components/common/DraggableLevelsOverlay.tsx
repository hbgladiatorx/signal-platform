import { useEffect, useRef, useState } from "react";
import { GripVertical, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";

export interface Levels {
  entry: number;
  stop: number;
  target: number;
}

interface Props {
  initial: Levels;
  direction: "LONG" | "SHORT";
  onChange?: (next: Levels) => void;
  className?: string;
}

/**
 * Editable strategy plan overlay rendered on top of a TradingView chart.
 * Each row (Target / Entry / Stop) is drag-to-adjust:
 *   - Vertical drag changes the level (~10px = 0.10%).
 *   - Entry shifts all three levels in lockstep (preserves the plan).
 *   - Target / Stop change their own % offset from entry.
 * Calls onChange on every move and on release.
 */
export function DraggableLevelsOverlay({ initial, direction, onChange, className }: Props) {
  const [levels, setLevels] = useState<Levels>(initial);
  // Re-sync if upstream signal changes
  const initKey = `${initial.entry}|${initial.stop}|${initial.target}`;
  useEffect(() => { setLevels(initial); }, [initKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const commit = (next: Levels) => {
    setLevels(next);
    onChange?.(next);
  };

  const reset = () => commit(initial);

  const targetPct = ((levels.target - levels.entry) / levels.entry) * 100;
  const stopPct = ((levels.stop - levels.entry) / levels.entry) * 100;
  const rr = Math.abs(targetPct / stopPct);
  const sign = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
  const fmt = (n: number) =>
    n >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 0 })
              : n.toLocaleString(undefined, { maximumFractionDigits: 2 });

  // Drag handlers — vertical drag adjusts price.
  // Up-drag (negative dy) raises the level; down-drag lowers it.
  // 1 px ≈ 0.01% of entry price (scaled), feels natural on hi-DPI screens.
  const startDrag = (
    e: React.PointerEvent,
    field: "entry" | "stop" | "target",
  ) => {
    e.preventDefault();
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    const startY = e.clientY;
    const start = { ...levels };
    const pxPerPct = 10; // 10px drag => 0.10% move on entry-equivalent

    const move = (ev: PointerEvent) => {
      const dy = startY - ev.clientY; // up = positive
      const pctDelta = dy / pxPerPct / 100;
      const factor = 1 + pctDelta;
      if (field === "entry") {
        // shift all levels uniformly
        commit({
          entry: +(start.entry * factor).toFixed(4),
          stop: +(start.stop * factor).toFixed(4),
          target: +(start.target * factor).toFixed(4),
        });
      } else {
        commit({ ...start, [field]: +(start[field] * factor).toFixed(4) });
      }
    };
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      try { (e.target as HTMLElement).releasePointerCapture(ev.pointerId); } catch {}
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div
      className={cn(
        "absolute right-3 top-3 z-10 w-[220px] rounded-lg border border-border/80 bg-background/90 p-2.5 font-mono text-[10px] backdrop-blur-md shadow-lg",
        className,
      )}
    >
      <div className="mb-1.5 flex items-center justify-between">
        <span className="tracking-[0.18em] text-muted-foreground">STRATEGY PLAN</span>
        <div className="flex items-center gap-1.5">
          <span className={direction === "LONG" ? "text-cyan" : "text-danger"}>{direction}</span>
          <button
            onClick={reset}
            title="Reset to original levels"
            className="rounded p-0.5 text-muted-foreground hover:bg-muted/40 hover:text-foreground"
          >
            <RotateCcw className="size-3" />
          </button>
        </div>
      </div>

      <DragRow
        label="Target" pct={sign(targetPct)} price={fmt(levels.target)} tone="cyan"
        onPointerDown={(e) => startDrag(e, "target")}
      />
      <DragRow
        label="Entry" pct="—" price={fmt(levels.entry)} tone="gold"
        onPointerDown={(e) => startDrag(e, "entry")}
      />
      <DragRow
        label="Stop" pct={sign(stopPct)} price={fmt(levels.stop)} tone="danger"
        onPointerDown={(e) => startDrag(e, "stop")}
      />

      <div className="mt-1.5 flex items-center justify-between border-t border-border/60 pt-1.5 text-muted-foreground">
        <span>R:R</span>
        <span className="text-foreground">{isFinite(rr) ? rr.toFixed(2) : "—"}</span>
      </div>
      <div className="mt-1 text-[9px] leading-tight text-muted-foreground">
        Drag <GripVertical className="-mt-0.5 inline size-2.5" /> rows up / down to adjust levels
      </div>
    </div>
  );
}

function DragRow({
  label, pct, price, tone, onPointerDown,
}: {
  label: string; pct: string; price: string;
  tone: "cyan" | "gold" | "danger";
  onPointerDown: (e: React.PointerEvent) => void;
}) {
  const cls = tone === "cyan" ? "text-cyan" : tone === "gold" ? "text-gold" : "text-danger";
  return (
    <div
      onPointerDown={onPointerDown}
      className="group flex cursor-ns-resize select-none items-center justify-between rounded px-1 py-0.5 hover:bg-muted/30"
    >
      <span className={cn("flex items-center gap-1", cls)}>
        <GripVertical className="size-2.5 opacity-60 group-hover:opacity-100" />
        {label}
      </span>
      <span className="flex items-baseline gap-2">
        <span className={cls}>{pct}</span>
        <span className="text-muted-foreground">{price}</span>
      </span>
    </div>
  );
}

export { Button as _Button }; // keep tree-shaker happy if not otherwise referenced
