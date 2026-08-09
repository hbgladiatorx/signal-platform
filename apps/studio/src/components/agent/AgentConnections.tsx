import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Bot, Server, Briefcase, Copy, Check, ExternalLink, Link2, Shield, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PLATFORMS, BAYN_MCP_URL, BROKER_MCP_URL,
  getConnections, setConnections, type ConnectionState, type AgentPlatform,
} from "@/lib/api/agent";
import { toast } from "sonner";

function useConn() {
  const [c, setC] = useState<ConnectionState>(getConnections());
  useEffect(() => {
    const fn = () => setC(getConnections());
    window.addEventListener("bayn.mcp.changed", fn);
    return () => window.removeEventListener("bayn.mcp.changed", fn);
  }, []);
  const update = (patch: Partial<ConnectionState>) => { const next = { ...c, ...patch }; setConnections(next); setC(next); };
  return [c, update] as const;
}

function StatusPill({ on, color = "cyan" }: { on: boolean; color?: "cyan" | "violet" | "gold" }) {
  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider",
      on
        ? color === "violet" ? "border-violet/40 bg-violet/10 text-violet"
        : color === "gold"   ? "border-gold/40 bg-gold/10 text-gold"
        : "border-success/40 bg-success/10 text-success"
        : "border-border bg-muted/30 text-muted-foreground",
    )}>
      <span className={cn("size-1.5 rounded-full", on ? "bg-current animate-pulse" : "bg-muted-foreground")} />
      {on ? "Connected" : "Not Connected"}
    </span>
  );
}

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1400); }}
      className="ml-2 inline-flex shrink-0 items-center gap-1 rounded border border-border bg-background px-2 py-1 text-[11px] hover:bg-muted/40"
    >
      {copied ? <Check className="size-3 text-success" /> : <Copy className="size-3" />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/** Card 1 — pick agent platform + show install command. */
function AgentCard() {
  const [conn, update] = useConn();
  const platform = (conn.platform ?? "claude-code") as AgentPlatform;
  const info = PLATFORMS.find((p) => p.id === platform)!;
  return (
    <Card className="flex flex-col gap-3 border-border bg-elevated p-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2"><Bot className="size-5 text-cyan" /><div className="font-medium">Your AI Agent</div></div>
        <StatusPill on={conn.agent} />
      </div>
      <div className="text-xs text-muted-foreground">Pick the platform your agent runs on. We'll show the exact install command.</div>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
        {PLATFORMS.map((p) => (
          <button key={p.id} onClick={() => update({ platform: p.id })}
            className={cn(
              "rounded-md border px-2 py-1.5 text-left text-[11px] transition-colors",
              platform === p.id ? "border-cyan/50 bg-cyan/10 text-foreground" : "border-border bg-background hover:border-cyan/30",
            )}>{p.name}</button>
        ))}
      </div>
      <div className="rounded-md border border-border bg-background p-2">
        <div className="mb-1 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">{info.name} · Bayn MCP install</div>
        <div className="flex items-start">
          <code className="flex-1 break-all font-mono text-[12px] text-foreground">{info.install}</code>
          <CopyBtn text={info.install} />
        </div>
      </div>
      <Button
        size="sm"
        variant={conn.agent ? "outline" : "default"}
        onClick={() => { update({ agent: !conn.agent }); toast(conn.agent ? "Agent disconnected" : "Agent connected (mock)"); }}
        className={!conn.agent ? "bg-cyan text-cyan-foreground hover:bg-cyan/90" : ""}
      >
        {conn.agent ? "Disconnect agent" : "Mark as connected"}
      </Button>
    </Card>
  );
}

/** Card 2 — Bayn MCP. */
function BaynCard() {
  const [conn, update] = useConn();
  return (
    <Card className="flex flex-col gap-3 border-border bg-elevated p-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2"><Server className="size-5 text-violet" /><div className="font-medium">Bayn MCP</div></div>
        <StatusPill on={conn.bayn} color="violet" />
      </div>
      <div className="rounded-md border border-border bg-background p-2 text-xs">
        <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Endpoint</div>
        <div className="flex items-start">
          <code className="flex-1 break-all font-mono text-[12px]">{BAYN_MCP_URL}</code>
          <CopyBtn text={BAYN_MCP_URL} />
        </div>
      </div>
      <div className="space-y-1 text-xs text-muted-foreground">
        <div className="font-medium text-foreground">What the agent can read</div>
        <ul className="ml-4 list-disc space-y-0.5">
          <li>Live signals from strategies you follow</li>
          <li>Strategy status &amp; verified performance</li>
          <li>Your taken-signal history (read-only)</li>
        </ul>
      </div>
      <div className="flex items-center justify-between rounded-md border border-border bg-background px-3 py-2">
        <div className="text-xs">Allow agent to read my signal feed</div>
        <Switch checked={conn.allowSignalRead} onCheckedChange={(v) => update({ allowSignalRead: v })} />
      </div>
      <Button size="sm" variant={conn.bayn ? "outline" : "default"}
        onClick={() => { update({ bayn: !conn.bayn }); toast(conn.bayn ? "Bayn MCP disconnected" : "Bayn MCP connected (mock)"); }}
        className={!conn.bayn ? "bg-violet text-violet-foreground hover:bg-violet/90" : ""}>
        {conn.bayn ? "Disconnect Bayn MCP" : "Connect Bayn MCP"}
      </Button>
    </Card>
  );
}

/** Card 3 — Brokerage Agent */
function BrokerageCard() {
  const [conn, update] = useConn();
  const [oauthOpen, setOauthOpen] = useState(false);
  return (
    <Card className="flex flex-col gap-3 border-border bg-elevated p-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2"><Briefcase className="size-5 text-gold" /><div className="font-medium">Brokerage Agent</div></div>
        <StatusPill on={conn.broker} color="gold" />
      </div>
      <div className="rounded-md border border-border bg-background p-2 text-xs">
        <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Endpoint</div>
        <div className="flex items-start">
          <code className="flex-1 break-all font-mono text-[12px]">{BROKER_MCP_URL}</code>
          <CopyBtn text={BROKER_MCP_URL} />
        </div>
      </div>
      <div className="space-y-1 text-xs text-muted-foreground">
        <div className="font-medium text-foreground">What Brokerage Agent does</div>
        <ul className="ml-4 list-disc space-y-0.5">
          <li>Read positions, balances, order history (Agentic account)</li>
          <li>Place orders <b>only</b> in your Agentic account</li>
          <li>Every trade requires your confirmation unless pre-authorized</li>
        </ul>
      </div>
      <Button size="sm" variant={conn.broker ? "outline" : "default"}
        onClick={() => conn.broker ? update({ broker: false }) : setOauthOpen(true)}
        className={!conn.broker ? "bg-gold text-gold-foreground hover:bg-gold/90" : ""}>
        {conn.broker ? "Disconnect Brokerage" : "Connect Brokerage Agent"}
      </Button>
      <a href={BROKER_MCP_URL} target="_blank" rel="noreferrer"
        className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
        <ExternalLink className="size-3" /> Brokerage Agent docs
      </a>

      {oauthOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-background/80 backdrop-blur" onClick={() => setOauthOpen(false)}>
          <Card className="m-4 max-w-md border-border bg-elevated p-5" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 text-sm font-semibold">Connect Brokerage Agent</div>
            <p className="text-xs text-muted-foreground">
              You'll be redirected to Brokerage to authorize your agent. The agent gets read access to positions, balances, and order history, and may place trades <b>only</b> in your Agentic account. You confirm each trade unless you pre-authorize a strategy.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setOauthOpen(false)}>Cancel</Button>
              <Button size="sm" className="bg-gold text-gold-foreground hover:bg-gold/90"
                onClick={() => { setOauthOpen(false); update({ broker: true }); toast.success("Brokerage Agent connected (mock)"); }}>
                Authorize (mock)
              </Button>
            </div>
          </Card>
        </div>
      )}
    </Card>
  );
}

/** Visual three-card loop with live connection lines. */
export function AgentLoopDiagram() {
  const [conn] = useConn();
  const left = conn.agent && conn.bayn;
  const right = conn.bayn && conn.broker;
  return (
    <div className="relative">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <AgentCard />
        <BaynCard />
        <BrokerageCard />
      </div>
      {/* desktop connector lines */}
      <div className="pointer-events-none absolute inset-x-0 top-1/2 hidden -translate-y-1/2 md:block">
        <div className="mx-auto grid max-w-full grid-cols-3 px-6">
          <div className="relative h-px"><div className={cn("absolute right-0 top-1/2 h-px w-1/4 -translate-y-1/2", left ? "bg-cyan" : "bg-border")} /></div>
          <div className="relative h-px"><div className={cn("absolute inset-x-0 top-1/2 h-px -translate-y-1/2", right ? "bg-gold" : left ? "bg-cyan" : "bg-border")} /></div>
          <div className="relative h-px"><div className={cn("absolute left-0 top-1/2 h-px w-1/4 -translate-y-1/2", right ? "bg-gold" : "bg-border")} /></div>
        </div>
      </div>
    </div>
  );
}

/** Read/write matrix across all three sides. */
export function PermissionMatrix() {
  const rows = [
    { k: "Read signals",      a: true,  b: true,  r: false },
    { k: "Read positions",    a: true,  b: false, r: true  },
    { k: "Read performance",  a: true,  b: true,  r: true  },
    { k: "Place trades",      a: false, b: false, r: true  },
    { k: "Confirm trades",    a: false, b: false, r: false, user: true },
    { k: "Custody funds",     a: false, b: false, r: true  },
  ];
  return (
    <Card className="border-border bg-elevated p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Shield className="size-4 text-violet" /> Permission Matrix
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] border-collapse text-xs">
          <thead>
            <tr className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
              <th className="py-1.5 text-left font-normal">Capability</th>
              <th className="py-1.5 text-center font-normal">Your Agent</th>
              <th className="py-1.5 text-center font-normal">Bayn</th>
              <th className="py-1.5 text-center font-normal">Brokerage</th>
              <th className="py-1.5 text-center font-normal">You</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.k} className="border-t border-border">
                <td className="py-2 text-foreground">{r.k}</td>
                <td className="py-2 text-center">{r.a ? <Check className="mx-auto size-3.5 text-success" /> : "—"}</td>
                <td className="py-2 text-center">{r.b ? <Check className="mx-auto size-3.5 text-success" /> : "—"}</td>
                <td className="py-2 text-center">{r.r ? <Check className="mx-auto size-3.5 text-success" /> : "—"}</td>
                <td className="py-2 text-center">{r.user ? <Check className="mx-auto size-3.5 text-success" /> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-start gap-2 rounded-md border border-warn/30 bg-warn/5 px-3 py-2 text-[11px] text-warn">
        <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
        <div className="text-foreground/80">
          <b className="text-warn">Bayn can never place trades.</b> Brokerage places trades only with your confirmation.
          Bayn is the brain, Brokerage is the hands, your agent is the nervous system connecting them.
        </div>
      </div>
    </Card>
  );
}

export function MCPConnectionSection() {
  return (
    <div className="space-y-4">
      <AgentLoopDiagram />
      <PermissionMatrix />
    </div>
  );
}

/** Pipeline deployability badge */
import type { DeployStage } from "@/lib/api/agent";
import { deployStageMeta } from "@/lib/api/agent";
export function DeployabilityBadge({ stage }: { stage: DeployStage }) {
  const m = deployStageMeta(stage);
  const tone = {
    danger: "border-danger/30 bg-danger/10 text-danger",
    warn:   "border-warn/30 bg-warn/10 text-warn",
    info:   "border-cyan/30 bg-cyan/10 text-cyan",
    ok:     "border-success/30 bg-success/10 text-success",
    violet: "border-violet/30 bg-violet/10 text-violet",
  }[m.tone];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium", tone)}>
      <span>{m.icon}</span>{m.label}
    </span>
  );
}

/** Optional small "connection status" widget for nav bar */
export function MCPMiniStatus() {
  const [conn] = useConn();
  const all = conn.agent && conn.bayn && conn.broker;
  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider",
      all ? "border-success/40 bg-success/10 text-success" : "border-border bg-muted/20 text-muted-foreground",
    )}>
      <Link2 className="size-3" /> Agentic loop · {all ? "live" : "incomplete"}
    </span>
  );
}
