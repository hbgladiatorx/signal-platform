import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Briefcase, Bitcoin, Building2, Activity, Check, Sparkles, Settings as SettingsIcon } from "lucide-react";
import { toast } from "sonner";
import { MCPConnectionSection } from "@/components/agent/AgentConnections";


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
  const [accountSize, setAccountSize] = useState(25000);

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-4 md:p-6">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>

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
    </div>
  );
}

export default SettingsPage;
