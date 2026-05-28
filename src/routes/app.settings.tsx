import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Briefcase, Bitcoin, Building2, Activity, Check, Sparkles, Settings as SettingsIcon, FlaskConical, ArrowRight } from "lucide-react";
import { toast } from "sonner";
import { MCPConnectionSection } from "@/components/agent/AgentConnections";
import { PlanBadge } from "@/components/billing/PlanBadge";
import { getCurrentPlan, getTier, setCurrentPlan } from "@/lib/api/billing";



export const Route = createFileRoute("/app/settings")({
  head: () => ({ meta: [{ title: "Settings — Bayn" }] }),
  component: SettingsPage,
});

const brokers = [
  { id: "coinbase", name: "Coinbase",     icon: Bitcoin,    desc: "Crypto spot — submit pre-filled orders to your account." },
  { id: "ibkr",     name: "Interactive Brokers", icon: Building2, desc: "Stocks & options worldwide." },
  { id: "tradier",  name: "Tradier",      icon: Briefcase,  desc: "US equities & options." },
  { id: "topstepx", name: "TopstepX",     icon: Activity,   desc: "Funded futures accounts." },
];

function SettingsPage() {
  const [connected, setConnected] = useState<Record<string, boolean>>({ coinbase: true });
  const [connected, setConnected] = useState<Record<string, boolean>>({ coinbase: true });
  const [accountSize, setAccountSize] = useState(25000);
  const [plan, setPlan] = useState(getCurrentPlan());
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
        </TabsList>

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


      <Card className="border-border bg-elevated p-5">
        <h2 className="font-semibold">Account</h2>
        <Separator className="my-4" />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-1.5"><Label>Display name</Label><Input defaultValue="Trader" className="bg-background" /></div>
          <div className="space-y-1.5"><Label>Email</Label><Input defaultValue="you@firm.com" className="bg-background" /></div>
        </div>
      </Card>

      <Card className="border-border bg-elevated p-5">
        <h2 className="font-semibold">Position sizing</h2>
        <p className="text-sm text-muted-foreground">Used to suggest size for each signal — based on a 1% account risk default.</p>
        <Separator className="my-4" />
        <div className="space-y-1.5">
          <Label>Account size (USD)</Label>
          <Input type="number" value={accountSize} onChange={(e) => setAccountSize(Number(e.target.value))} className="bg-background" />
        </div>
      </Card>

      <Card className="border-border bg-elevated p-5">
        <h2 className="font-semibold">Broker connections</h2>
        <p className="text-sm text-muted-foreground">Connect a broker to one-click pre-fill orders. Bayn never trades automatically.</p>
        <Separator className="my-4" />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {brokers.map((b) => {
            const Icon = b.icon;
            const isOn = !!connected[b.id];
            return (
              <Card key={b.id} className="flex items-start gap-3 border-border bg-background/40 p-4">
                <Icon className="mt-0.5 size-5 text-cyan" />
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <div className="font-medium">{b.name}</div>
                    {isOn ? <span className="inline-flex items-center gap-1 text-xs text-cyan"><Check className="size-3" /> Connected</span> : null}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{b.desc}</p>
                  <Button size="sm" variant={isOn ? "outline" : "default"} className="mt-3"
                    onClick={() => { setConnected((p) => ({ ...p, [b.id]: !p[b.id] })); toast(isOn ? `${b.name} disconnected` : `${b.name} connected (mock)`); }}>
                    {isOn ? "Disconnect" : "Connect"}
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      </Card>

      <Card className="border-border bg-elevated p-5">
        <h2 className="font-semibold">Notifications</h2>
        <Separator className="my-4" />
        <div className="space-y-3">
          {["New signal from followed strategy", "Signal hit target", "Signal hit stop", "Weekly performance summary"].map((label) => (
            <div key={label} className="flex items-center justify-between">
              <Label>{label}</Label>
              <Switch defaultChecked />
            </div>
          ))}
        </div>
      </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}


export default SettingsPage;
