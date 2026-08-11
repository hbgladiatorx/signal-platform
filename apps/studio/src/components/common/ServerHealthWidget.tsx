// Floating, draggable server-health monitor. Polls /system/metrics every 2s
// while open, so a running backtest (CPU/memory spike on the host) shows up live.
// CPU + memory reflect the whole host; network is derived as a rate from
// successive samples. Position + open state persist in localStorage.
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSystemMetrics, type SystemMetrics } from "@/lib/api/system";
import { cn } from "@/lib/utils";
import { Activity, X, Minus, GripVertical, Cpu, MemoryStick, HardDrive, Network } from "lucide-react";

const POS_KEY = "studio.health.pos";
const OPEN_KEY = "studio.health.open";

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${u[i]}`;
}
const fmtRate = (bytesPerSec: number) => `${fmtBytes(Math.max(0, bytesPerSec))}/s`;

const toneFor = (pct: number) =>
  pct >= 85 ? "bg-red-500" : pct >= 70 ? "bg-amber-500" : "bg-emerald-500";

function Meter({ icon: Icon, label, pct, detail }: {
  icon: typeof Cpu; label: string; pct: number; detail: string;
}) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px]">
        <span className="flex items-center gap-1 text-muted-foreground"><Icon className="size-3" /> {label}</span>
        <span className="font-mono tabular-nums">{clamped.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full transition-all", toneFor(clamped))} style={{ width: `${clamped}%` }} />
      </div>
      <div className="text-right font-mono text-[10px] text-muted-foreground">{detail}</div>
    </div>
  );
}

export function ServerHealthWidget() {
  const [open, setOpen] = useState<boolean>(() => {
    try { return localStorage.getItem(OPEN_KEY) === "1"; } catch { return false; }
  });
  const [pos, setPos] = useState<{ x: number; y: number }>(() => {
    try {
      const s = localStorage.getItem(POS_KEY);
      if (s) return JSON.parse(s);
    } catch { /* ignore */ }
    return { x: 16, y: 16 }; // offset from bottom-right
  });
  const drag = useRef<{ dx: number; dy: number } | null>(null);

  useEffect(() => { try { localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch { /* ignore */ } }, [open]);
  useEffect(() => { try { localStorage.setItem(POS_KEY, JSON.stringify(pos)); } catch { /* ignore */ } }, [pos]);

  const { data, error } = useQuery({
    queryKey: ["systemMetrics"],
    queryFn: getSystemMetrics,
    refetchInterval: 2000,
    enabled: open,
  });

  // Derive network rate from the previous sample.
  const prev = useRef<SystemMetrics | null>(null);
  const [net, setNet] = useState<{ up: number; down: number }>({ up: 0, down: 0 });
  useEffect(() => {
    if (!data) return;
    const p = prev.current;
    if (p && data.ts > p.ts) {
      const dt = data.ts - p.ts;
      setNet({
        up: (data.net_bytes_sent - p.net_bytes_sent) / dt,
        down: (data.net_bytes_recv - p.net_bytes_recv) / dt,
      });
    }
    prev.current = data;
  }, [data]);

  const onPointerDown = (e: React.PointerEvent) => {
    // Position is anchored bottom-right; convert to that frame while dragging.
    const rx = window.innerWidth - e.clientX - pos.x;
    const ry = window.innerHeight - e.clientY - pos.y;
    drag.current = { dx: rx, dy: ry };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const x = Math.max(4, window.innerWidth - e.clientX - drag.current.dx);
    const y = Math.max(4, window.innerHeight - e.clientY - drag.current.dy);
    setPos({ x, y });
  };
  const onPointerUp = () => { drag.current = null; };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        title="Server health"
        className="fixed z-50 flex items-center gap-1.5 rounded-full border border-border bg-elevated px-3 py-1.5 text-xs shadow-lg transition-colors hover:border-violet/40"
        style={{ right: pos.x, bottom: pos.y }}
      >
        <Activity className="size-3.5 text-emerald-500" /> Server
      </button>
    );
  }

  return (
    <div
      className="fixed z-50 w-60 rounded-lg border border-border bg-elevated/95 shadow-xl backdrop-blur"
      style={{ right: pos.x, bottom: pos.y }}
    >
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        className="flex cursor-grab items-center justify-between gap-2 border-b border-border px-2.5 py-1.5 active:cursor-grabbing"
      >
        <span className="flex items-center gap-1.5 text-xs font-medium">
          <GripVertical className="size-3.5 text-muted-foreground" /> Server health
        </span>
        <div className="flex items-center gap-0.5">
          <button className="rounded p-0.5 text-muted-foreground hover:text-foreground" title="Minimize" onClick={() => setOpen(false)}>
            <Minus className="size-3.5" />
          </button>
          <button className="rounded p-0.5 text-muted-foreground hover:text-foreground" title="Close" onClick={() => setOpen(false)}>
            <X className="size-3.5" />
          </button>
        </div>
      </div>

      <div className="space-y-3 p-3">
        {error ? (
          <p className="text-[11px] text-muted-foreground">Metrics unavailable. {(error as Error).message}</p>
        ) : !data ? (
          <p className="text-[11px] text-muted-foreground">Reading…</p>
        ) : (
          <>
            <Meter
              icon={Cpu} label="CPU" pct={data.cpu_percent}
              detail={`${data.cpu_cores} cores${data.load_avg ? ` · load ${data.load_avg[0].toFixed(2)}` : ""}`}
            />
            <Meter
              icon={MemoryStick} label="Memory" pct={data.mem_percent}
              detail={`${fmtBytes(data.mem_used)} / ${fmtBytes(data.mem_total)}`}
            />
            <Meter
              icon={HardDrive} label="Disk" pct={data.disk_percent}
              detail={`${fmtBytes(data.disk_used)} / ${fmtBytes(data.disk_total)}`}
            />
            <div className="flex items-center justify-between border-t border-border pt-2 text-[11px]">
              <span className="flex items-center gap-1 text-muted-foreground"><Network className="size-3" /> Network</span>
              <span className="font-mono tabular-nums text-muted-foreground">
                ↑{fmtRate(net.up)} ↓{fmtRate(net.down)}
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default ServerHealthWidget;
