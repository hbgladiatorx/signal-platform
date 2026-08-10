import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Sparkles, Settings as SettingsIcon, FlaskConical, ArrowRight, Plug, CheckCircle2, Circle } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { MCPConnectionSection } from "@/components/agent/AgentConnections";
import { ApiCredentialsCard } from "@/components/settings/ApiCredentialsCard";
import { PlanBadge } from "@/components/billing/PlanBadge";
import { getCurrentPlan, getTier, setCurrentPlan } from "@/lib/api/billing";
import { getConnections } from "@/lib/api/system";
import { getFinnhubStatus } from "@/lib/api/finnhub.functions";
import { useAccountSize, useIdentity, useNotifications } from "@/lib/user-prefs";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";



export const Route = createFileRoute("/app/settings")({
  head: () => ({ meta: [{ title: "Settings — Bayn" }] }),
  component: SettingsPage,
});

function SettingsPage() {
  const [accountSize, setAccountSize] = useAccountSize();
  const [identity, setIdentity] = useIdentity();
  const [notifs, setNotifs] = useNotifications();
  const { user } = useAuth();
  const [plan, setPlan] = useState(getCurrentPlan());

  const notifItems: { key: keyof typeof notifs; label: string }[] = [
    { key: "signalFired", label: "New signal from followed strategy" },
    { key: "signalHitTarget", label: "Signal hit target" },
    { key: "signalHitStop", label: "Signal hit stop" },
    { key: "weeklySummary", label: "Weekly performance summary" },
  ];
  const traderTier = plan.trader ? getTier(plan.trader) : null;
  const studioTier = plan.developer ? getTier(plan.developer) : null;

  const addStudio = () => {
    setCurrentPlan({ developer: "studio-builder" });
    setPlan(getCurrentPlan());
    toast.success("Studio Builder added — open My Studio to start building");
  };
  const removeStudio = () => {
    setCurrentPlan({ developer: null });
    setPlan(getCurrentPlan());
    toast("Studio removed from your account");
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 md:p-6">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>

      <Tabs defaultValue="general">
        <TabsList>
          <TabsTrigger value="general"><SettingsIcon className="mr-1.5 size-3.5" /> General</TabsTrigger>
          <TabsTrigger value="plan"><Sparkles className="mr-1.5 size-3.5 text-cyan" /> Plan</TabsTrigger>
          <TabsTrigger value="agent"><Sparkles className="mr-1.5 size-3.5 text-violet" /> AI Agent</TabsTrigger>
          <TabsTrigger value="connections"><Plug className="mr-1.5 size-3.5 text-emerald-500" /> Connections</TabsTrigger>
        </TabsList>

        <TabsContent value="connections" className="mt-4">
          <ConnectionsPanel />
        </TabsContent>

        <TabsContent value="plan" className="mt-4 space-y-4">
          <Card className="border-border bg-elevated p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">Trader plan</h2>
                <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
                  Current: <PlanBadge tier={plan.trader} />
                  {traderTier && <span>· ${traderTier.monthly}/mo</span>}
                </p>
              </div>
              <Button asChild variant="outline" size="sm">
                <Link to="/app/pricing">Manage <ArrowRight className="ml-1 size-3" /></Link>
              </Button>
            </div>
          </Card>

          <Card className={`border bg-elevated p-5 ${studioTier ? "border-violet/30" : "border-border"}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-start gap-3">
                <div className="grid size-10 place-items-center rounded-md bg-violet/15 text-violet">
                  <FlaskConical className="size-5" />
                </div>
                <div>
                  <h2 className="font-semibold">Studio access</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    The private strategy lab — node-based builder, backtests, forward tests, and personal signals.
                  </p>
                  {studioTier ? (
                    <p className="mt-2 flex items-center gap-2 text-sm">
                      <PlanBadge tier={plan.developer} />
                      <span className="text-muted-foreground">· ${studioTier.monthly}/mo</span>
                    </p>
                  ) : (
                    <p className="mt-2 text-xs text-muted-foreground">
                      Not on your account. Add Builder ($299/mo) to get started, or pick a higher tier.
                    </p>
                  )}
                </div>
              </div>
              <div className="flex flex-col gap-2">
                {studioTier ? (
                  <>
                    <Button asChild size="sm" variant="outline">
                      <Link to="/studio/pricing">Change tier</Link>
                    </Button>
                    <Button size="sm" variant="ghost" onClick={removeStudio}>Remove</Button>
                  </>
                ) : (
                  <>
                    <Button size="sm" onClick={addStudio} className="bg-violet text-violet-foreground hover:bg-violet/90">
                      Add Studio Builder
                    </Button>
                    <Button asChild size="sm" variant="ghost">
                      <Link to="/studio/pricing">Compare tiers</Link>
                    </Button>
                  </>
                )}
              </div>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="agent" className="mt-4 space-y-4">
          <div>
            <h2 className="text-lg font-semibold">Agentic loop</h2>
            <p className="text-sm text-muted-foreground">
              Bayn is the brain, Brokerage is the hands, your agent is the nervous system. Connect all three to close the loop.
            </p>
          </div>
          <MCPConnectionSection />
        </TabsContent>

        <TabsContent value="general" className="mt-4 space-y-6">

      <Card className="border-border bg-elevated p-5">
        <h2 className="font-semibold">Account</h2>
        <Separator className="my-4" />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Display name</Label>
            <Input
              value={identity.displayName}
              onChange={(e) => setIdentity({ ...identity, displayName: e.target.value })}
              placeholder="Your name"
              className="bg-background"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Email</Label>
            <Input value={user?.email ?? ""} readOnly disabled className="bg-background" />
          </div>
        </div>
      </Card>

      <Card className="border-border bg-elevated p-5">
        <h2 className="font-semibold">Position sizing</h2>
        <p className="text-sm text-muted-foreground">Used to suggest size for each signal — based on a 1% account risk default.</p>
        <Separator className="my-4" />
        <div className="space-y-1.5">
          <Label>Account size (USD)</Label>
          <Input type="number" value={accountSize || ""} onChange={(e) => setAccountSize(Number(e.target.value) || 0)} placeholder="25000" className="bg-background" />
        </div>
      </Card>

      <ApiCredentialsCard />

      <Card className="border-border bg-elevated p-5">
        <h2 className="font-semibold">Notifications</h2>
        <Separator className="my-4" />
        <div className="space-y-3">
          {notifItems.map((it) => (
            <div key={it.key} className="flex items-center justify-between">
              <Label>{it.label}</Label>
              <Switch checked={notifs[it.key]} onCheckedChange={(v) => setNotifs({ ...notifs, [it.key]: v })} />
            </div>
          ))}
        </div>
      </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}


function ConnectionsPanel() {
  const conn = useQuery({ queryKey: ["connections"], queryFn: getConnections });
  const finnhubFn = useServerFn(getFinnhubStatus);
  const finnhub = useQuery({ queryKey: ["finnhub-status"], queryFn: () => finnhubFn() });
  const c = conn.data;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        What's configured on the server. Green = ready; grey = not set. Values are never shown here —
        keys live in the server <code className="font-mono text-xs">.env</code> and in your API credentials.
      </p>

      <Card className="border-border bg-elevated p-5">
        <h2 className="font-semibold">Data &amp; AI</h2>
        <Separator className="my-3" />
        <div className="divide-y divide-border">
          <StatusRow ok label="Sign-in & data (Supabase)" hint="Built in — always on." />
          <StatusRow ok={c?.ai_copilot} loading={conn.isLoading} label="AI Copilot (Anthropic)" hint="Studio strategy builder + analysis." />
          <StatusRow ok={c?.crypto_data} loading={conn.isLoading} label="Crypto market data (Binance.US)" hint="Live crypto prices for charts, signals, backtests." />
          <StatusRow ok={c?.stock_data_alpaca} loading={conn.isLoading} label="Stock market data (Alpaca IEX)" hint="Free stock feed — powers stock charts + paper trading." />
          <StatusRow ok={c?.stock_data_polygon} loading={conn.isLoading} optional label="Stock market data (Polygon)" hint="Optional paid real-time feed. Not needed if Alpaca is on." />
          <StatusRow ok={finnhub.data?.configured} loading={finnhub.isLoading} label="News & ticker lookup (Finnhub)" hint="News wire + 'add ticker' validation." />
        </div>
      </Card>

      <Card className="border-border bg-elevated p-5">
        <h2 className="font-semibold">Trading &amp; security</h2>
        <Separator className="my-3" />
        <div className="divide-y divide-border">
          <StatusRow ok={c?.trading_alpaca_paper} loading={conn.isLoading} label="Shared paper trading (Alpaca)" hint="Lets you paper-trade stocks without your own key." />
          <StatusRow ok={c?.trading_binanceus} loading={conn.isLoading} label="Live crypto trading (Binance.US)" hint="Real-money crypto execution." />
          <StatusRow ok={c?.key_encryption} loading={conn.isLoading} label="Key encryption" hint="Required before you can save your own broker keys." />
        </div>
      </Card>

      {conn.isError && (
        <p className="text-sm text-danger">
          Couldn't load connection status{conn.error instanceof Error ? `: ${conn.error.message}` : ""}.
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        Your personal broker keys are managed under the <b>General</b> tab (API credentials).
      </p>
    </div>
  );
}

function StatusRow({ ok, loading, label, hint, optional }: { ok?: boolean; loading?: boolean; label: string; hint: string; optional?: boolean }) {
  return (
    <div className="flex items-center gap-3 py-3">
      <span className="shrink-0">
        {loading ? <Circle className="size-4 animate-pulse text-muted-foreground" />
          : ok ? <CheckCircle2 className="size-4 text-emerald-500" />
          : <Circle className="size-4 text-muted-foreground" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">{hint}</div>
      </div>
      <span className={cn(
        "shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide",
        loading ? "border-border text-muted-foreground"
          : ok ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-500"
          : optional ? "border-border text-muted-foreground"
          : "border-amber-500/40 bg-amber-500/10 text-amber-500",
      )}>
        {loading ? "…" : ok ? "Configured" : optional ? "Optional" : "Not set"}
      </span>
    </div>
  );
}

export default SettingsPage;
