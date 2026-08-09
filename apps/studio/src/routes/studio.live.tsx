import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Activity, ShieldAlert, ShieldCheck, Square, CircleStop } from "lucide-react";
import {
  listSessions, getSession, getSessionOrders, getSessionPositions, getSessionEquity,
  stopSession, flattenSession, getKillSwitch, engageKillSwitch, disengageKillSwitch,
  type PaperSessionSummary,
} from "@/lib/api/sessions";

export const Route = createFileRoute("/studio/live")({
  head: () => ({ meta: [{ title: "Live & Paper — Bayn Studio" }] }),
  component: LiveSessions,
});

const REFRESH = 5000; // ms — live polling cadence
const n = (v: unknown) => (typeof v === "number" ? v : Number(v) || 0);
const money = (v: unknown) => `$${n(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

function LiveSessions() {
  const { data: sessions, isLoading } = useQuery({
    queryKey: ["sessions"],
    queryFn: listSessions,
    refetchInterval: REFRESH,
  });

  const [selected, setSelected] = useState<string | undefined>();
  useEffect(() => {
    if (!selected && sessions?.length) setSelected(sessions[0].id);
  }, [sessions, selected]);

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Live &amp; Paper</h1>
          <p className="text-sm text-muted-foreground">
            Strategies running against live market data. Orders, fills and equity update every few seconds.
          </p>
        </div>
        <KillSwitch />
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading sessions…</p>
      ) : !sessions?.length ? (
        <Card className="border-dashed border-border bg-elevated/40 p-10 text-center text-sm text-muted-foreground">
          <Activity className="mx-auto mb-2 size-8 opacity-50" />
          No live or paper sessions yet. Deploy a strategy from its backtest to start one.
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
          <div className="space-y-2">
            {sessions.map((s) => (
              <SessionCard key={s.id} s={s} active={s.id === selected} onClick={() => setSelected(s.id)} />
            ))}
          </div>
          {selected ? <SessionDetail id={selected} /> : null}
        </div>
      )}
    </div>
  );
}

function statusTone(status: string) {
  if (status === "running") return "text-emerald-400";
  if (status === "failed" || status === "error") return "text-destructive";
  return "text-muted-foreground";
}

function SessionCard({ s, active, onClick }: { s: PaperSessionSummary; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`w-full rounded-md border p-3 text-left transition-colors ${
        active ? "border-violet/50 bg-elevated" : "border-border bg-elevated/40 hover:border-violet/30"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-medium">{s.strategy_name}</span>
        <Badge variant={s.mode === "live" ? "destructive" : "secondary"}>{s.mode}</Badge>
      </div>
      <div className="mt-1 flex items-center gap-2 text-xs">
        <span className={statusTone(s.status)}>● {s.status}</span>
        <span className="text-muted-foreground">· {s.symbols.length} sym · {s.num_fills} fills</span>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        {s.current_equity != null ? `${money(s.current_equity)} equity` : "—"}
        {" · "}
        {formatDistanceToNow(new Date(s.created_at), { addSuffix: true })}
      </div>
    </button>
  );
}

function SessionDetail({ id }: { id: string }) {
  const qc = useQueryClient();
  const common = { refetchInterval: REFRESH, enabled: !!id };
  const { data: s } = useQuery({ queryKey: ["session", id], queryFn: () => getSession(id), ...common });
  const { data: orders } = useQuery({ queryKey: ["session-orders", id], queryFn: () => getSessionOrders(id), ...common });
  const { data: positions } = useQuery({ queryKey: ["session-positions", id], queryFn: () => getSessionPositions(id), ...common });
  const { data: equity } = useQuery({ queryKey: ["session-equity", id], queryFn: () => getSessionEquity(id), ...common });

  const refresh = () => {
    ["session", "session-orders", "session-positions", "session-equity", "sessions"].forEach((k) =>
      qc.invalidateQueries({ queryKey: k === "sessions" ? ["sessions"] : [k, id] }),
    );
  };

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); toast.success(ok); refresh(); }
    catch (e) { toast.error(e instanceof Error ? e.message : "Action failed"); }
  };

  const last = equity?.length ? equity[equity.length - 1] : undefined;
  const isRunning = s?.status === "running";

  return (
    <div className="space-y-4">
      <Card className="border-border bg-elevated p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-semibold">{s?.strategy_name ?? "Session"}</h2>
              {s && <Badge variant={s.mode === "live" ? "destructive" : "secondary"}>{s.mode}</Badge>}
              {s && <span className={`text-xs ${statusTone(s.status)}`}>● {s.status}</span>}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{s?.symbols.join(", ")}</p>
          </div>
          {isRunning && (
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => act(() => flattenSession(id), "Flatten requested")}>
                <Square className="mr-1 size-3.5" /> Flatten
              </Button>
              <Button size="sm" variant="destructive" onClick={() => act(() => stopSession(id), "Stop requested")}>
                <CircleStop className="mr-1 size-3.5" /> Stop
              </Button>
            </div>
          )}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 border-t border-border pt-3 sm:grid-cols-4">
          <Stat label="Equity" value={last ? money(last.total_equity) : s?.current_equity != null ? money(s.current_equity) : "—"} />
          <Stat label="Realized P&L" value={s?.realized_pnl != null ? money(s.realized_pnl) : "—"} />
          <Stat label="Orders" value={String(s?.num_orders ?? 0)} />
          <Stat label="Fills" value={String(s?.num_fills ?? 0)} />
        </div>
      </Card>

      <Card className="border-border bg-elevated p-4">
        <h3 className="mb-2 text-sm font-semibold">Open positions</h3>
        {!positions?.length ? (
          <p className="text-xs text-muted-foreground">No open positions.</p>
        ) : (
          <Table head={["Symbol", "Qty", "Avg cost", "Realized P&L"]}>
            {positions.map((p) => (
              <tr key={p.symbol} className="border-t border-border">
                <td className="p-2 font-mono text-xs">{p.symbol}</td>
                <td className="p-2 text-right">{n(p.quantity)}</td>
                <td className="p-2 text-right">{money(p.avg_cost)}</td>
                <td className={`p-2 text-right ${n(p.realized_pnl) >= 0 ? "text-emerald-400" : "text-destructive"}`}>{money(p.realized_pnl)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card className="border-border bg-elevated p-4">
        <h3 className="mb-2 text-sm font-semibold">Recent orders</h3>
        {!orders?.length ? (
          <p className="text-xs text-muted-foreground">No orders yet.</p>
        ) : (
          <Table head={["Time", "Symbol", "Side", "Qty", "Status", "Fill"]}>
            {[...orders].slice(-40).reverse().map((o) => (
              <tr key={o.id} className="border-t border-border">
                <td className="p-2 text-xs text-muted-foreground">{new Date(o.submitted_ts).toLocaleTimeString()}</td>
                <td className="p-2 font-mono text-xs">{o.symbol}</td>
                <td className={`p-2 ${o.side?.toLowerCase() === "sell" ? "text-destructive" : "text-emerald-400"}`}>{o.side}</td>
                <td className="p-2 text-right">{n(o.quantity)}</td>
                <td className="p-2 text-xs">{o.status}{o.error_message ? ` (${o.error_message})` : ""}</td>
                <td className="p-2 text-right text-xs">{o.avg_fill_price != null ? money(o.avg_fill_price) : "—"}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-0.5 font-mono text-lg">{value}</div>
    </div>
  );
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-muted-foreground">
            {head.map((h, i) => (
              <th key={h} className={`p-2 ${i === 0 || i === 1 ? "text-left" : "text-right"}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function KillSwitch() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["killswitch"], queryFn: getKillSwitch, refetchInterval: REFRESH });
  const engaged = !!data?.engaged;

  const toggle = async () => {
    try {
      if (engaged) { await disengageKillSwitch(); toast.success("Kill switch disengaged — live trading resumes"); }
      else { await engageKillSwitch(); toast("Kill switch engaged — live order submission halted"); }
      qc.invalidateQueries({ queryKey: ["killswitch"] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Kill switch toggle failed");
    }
  };

  return (
    <Button variant={engaged ? "destructive" : "outline"} size="sm" onClick={toggle}>
      {engaged ? <><ShieldAlert className="mr-1 size-4" /> Kill switch ON</> : <><ShieldCheck className="mr-1 size-4" /> Kill switch off</>}
    </Button>
  );
}
