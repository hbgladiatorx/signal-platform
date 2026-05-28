import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ArrowRight, ArrowLeft, Check, Sparkles, BadgeCheck, Layers, BarChart3,
  Bot, Zap, ShieldCheck, LineChart, Wand2, Workflow,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { BillingToggle } from "@/components/billing/BillingToggle";
import { PricingTable } from "@/components/billing/PricingTable";
import { setCurrentPlan, type Billing, type TierId } from "@/lib/api/billing";
import {
  setTraderSeeded, setStudioSeeded, setOnboarded, toggleFollow,
  setEnabledAssetClasses, setLiveTrackingStrategy,
} from "@/lib/user-prefs";

// Map asset class → the free verified strategy id activated for new traders.
const FREE_STRATEGY_BY_ASSET: Record<Asset, string> = {
  stocks: "s-meanrev-spy",
  crypto: "s-btc-hourly-mr",
  options: "s-spy-otm-put",
  futures: "s-mes-orb",
};

export const Route = createFileRoute("/onboarding")({
  head: () => ({ meta: [{ title: "Welcome to Bayn" }] }),
  component: OnboardingPage,
});

type Path = "trader" | "developer" | "both";
type Asset = "stocks" | "crypto" | "options" | "futures";
type Experience = "retail" | "active" | "professional";

const ASSETS: { key: Asset; label: string }[] = [
  { key: "stocks", label: "Stocks" },
  { key: "crypto", label: "Crypto" },
  { key: "options", label: "Options" },
  { key: "futures", label: "Futures" },
];

function OnboardingPage() {
  const nav = useNavigate();
  const [authChecked, setAuthChecked] = useState(false);
  const [step, setStep] = useState(1);
  const [path, setPath] = useState<Path>("trader");
  const [assets, setAssets] = useState<Asset[]>(["stocks", "crypto"]);
  const [experience, setExperience] = useState<Experience>("active");
  const [accountSize, setAccountSize] = useState("100000");
  const [riskPct, setRiskPct] = useState("1");
  const [goals, setGoals] = useState<string[]>(["consistent income"]);
  const [billing, setBilling] = useState<Billing>("annual");

  // After step 6, developers get the Studio intro (step 7), then land.
  const totalSteps = path === "trader" ? 7 : 8;

  const activateTrader = () => {
    // Add the user's free verified strategies to their followed list, then mark seeded.
    const chosen = (assets.length ? assets : (ASSETS.map(a => a.key) as Asset[]));
    chosen.forEach((a) => toggleFollow(FREE_STRATEGY_BY_ASSET[a], true));
    setEnabledAssetClasses(chosen);
    // Pin the first free strategy as the Live Tracking default.
    if (chosen.length) setLiveTrackingStrategy(FREE_STRATEGY_BY_ASSET[chosen[0]]);
    setTraderSeeded(true);
  };

  // NOTE: onboarded is only flipped to true inside finish(). Marking it on
  // mount would let users skip the flow by refreshing — AuthGate would then
  // route them straight into the app.

  const next = () => {
    setStep((s) => {
      const nextStep = Math.min(s + 1, totalSteps);
      if (s === 4 && (path === "trader" || path === "both")) activateTrader();
      return nextStep;
    });
  };
  const back = () => setStep((s) => Math.max(s - 1, 1));

  const finish = () => {
    if ((path === "trader" || path === "both")) activateTrader();
    if (path === "developer" || path === "both") setStudioSeeded(true);
    setOnboarded(true);
    if (path === "developer" || path === "both") nav({ to: "/studio/home" });
    else nav({ to: "/app/home" });
  };

  // Onboarding requires an account. Anonymous visitors get bounced to /auth.
  useEffect(() => {
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      if (!data.session) nav({ to: "/auth" });
      else setAuthChecked(true);
    });
    return () => { active = false; };
  }, [nav]);

  if (!authChecked) {
    return (
      <div className="grid min-h-screen place-items-center bg-background">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }


  return (
    <div className="min-h-screen bg-background text-foreground" style={{ fontFamily: "var(--font-landing-body)" }}>
      <header className="border-b border-border/40">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4 md:px-10">
          <Link to="/" className="flex items-center gap-2.5 text-base font-semibold">
            <div className="grid size-8 place-items-center rounded-lg font-bold text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}>B</div>
            <span style={{ fontFamily: "var(--font-landing-display)", letterSpacing: "-0.02em" }}>Bayn</span>
          </Link>
          <button onClick={finish} className="text-xs text-muted-foreground hover:text-foreground">
            Skip onboarding
          </button>
        </div>
        <div className="mx-auto max-w-5xl px-6 pb-4 md:px-10">
          <ProgressBar step={step} total={totalSteps} />
          <div className="mt-2 text-[11px] uppercase tracking-wider text-muted-foreground">
            Step {step} of {totalSteps}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-10 md:px-10 md:py-16">
        {step === 1 && (
          <Step title="Trader or Studio?"
            sub="Pick the path that fits today — you can add the other later. Studio is paid-only; Trader has a free tier with 4 verified strategies.">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <PathCard
                active={path === "trader"} onClick={() => setPath("trader")}
                icon={BadgeCheck} accent="cyan" title="Trader"
                sub="Follow verified strategies. Free tier included; upgrade for premium catalog access."
              />
              <PathCard
                active={path === "developer"} onClick={() => setPath("developer")}
                icon={Layers} accent="violet" title="Studio"
                sub="Build your own strategies. Node editor, backtests, forward-tests. Paid plan required."
              />
              <PathCard
                active={path === "both"} onClick={() => setPath("both")}
                icon={Sparkles} accent="emerald" title="Both"
                sub="Trader feed first, then Studio intro. Studio plan still required for the builder."
              />
            </div>
          </Step>
        )}

        {step === 2 && (
          <Step title="Tell us your operator profile" sub="Drives strategy recommendations and position sizing.">
            <div className="space-y-6">
              <Group label="Asset classes (multi-select)">
                <div className="flex flex-wrap gap-2">
                  {ASSETS.map((a) => {
                    const on = assets.includes(a.key);
                    return (
                      <button key={a.key}
                        onClick={() => setAssets(on ? assets.filter(x => x !== a.key) : [...assets, a.key])}
                        className={cn("rounded-full border px-3.5 py-1.5 text-sm transition-colors",
                          on ? "border-cyan/50 bg-cyan/15 text-cyan" : "border-border bg-elevated text-muted-foreground hover:text-foreground")}>
                        {a.label}
                      </button>
                    );
                  })}
                </div>
              </Group>
              <Group label="Experience">
                <div className="grid grid-cols-3 gap-2">
                  {(["retail", "active", "professional"] as Experience[]).map((e) => (
                    <button key={e} onClick={() => setExperience(e)}
                      className={cn("rounded-lg border px-3 py-2 text-sm capitalize transition-colors",
                        experience === e ? "border-cyan/50 bg-cyan/15 text-cyan" : "border-border bg-elevated text-muted-foreground hover:text-foreground")}>
                      {e}
                    </button>
                  ))}
                </div>
              </Group>
              <Group label="Goals (multi-select)">
                <div className="flex flex-wrap gap-2">
                  {["consistent income", "growth", "learning", "automation"].map((g) => {
                    const on = goals.includes(g);
                    return (
                      <button key={g}
                        onClick={() => setGoals(on ? goals.filter(x => x !== g) : [...goals, g])}
                        className={cn("rounded-full border px-3 py-1.5 text-sm capitalize transition-colors",
                          on ? "border-cyan/50 bg-cyan/15 text-cyan" : "border-border bg-elevated text-muted-foreground hover:text-foreground")}>
                        {g}
                      </button>
                    );
                  })}
                </div>
              </Group>
            </div>
          </Step>
        )}

        {step === 3 && (
          <Step title="Risk & position sizing"
            sub="Powers the suggested position size on every signal. You can change this later in Settings.">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Group label="Account size (USD)">
                <Input value={accountSize} onChange={(e) => setAccountSize(e.target.value.replace(/[^0-9]/g, ""))}
                  inputMode="numeric" className="h-11 bg-elevated" />
              </Group>
              <Group label="Default risk per trade (%)">
                <Input value={riskPct} onChange={(e) => setRiskPct(e.target.value.replace(/[^0-9.]/g, ""))}
                  inputMode="decimal" className="h-11 bg-elevated" />
              </Group>
            </div>
            <div className="mt-5 flex items-start gap-2 rounded-lg border border-border bg-elevated p-3 text-xs text-muted-foreground">
              <ShieldCheck className="mt-0.5 size-4 shrink-0" style={{ color: "var(--emerald-glow)" }} />
              Bayn never trades for you. We compute suggested size — you execute.
            </div>
          </Step>
        )}

        {step === 4 && (
          <Step title="Your free verified strategies are live"
            sub="One per asset class — the foundation tier of the catalog. Real, tracked, free forever.">
            <FreeStrategyActivation assets={assets.length ? assets : ASSETS.map(a => a.key)} />
          </Step>
        )}

        {step === 5 && (
          <Step title="Connect your agent" sub="Optional. Hook up an AI agent + Robinhood Agentic to run the full loop.">
            <AgentLoopDiagram />
            <div className="mt-6 rounded-xl border border-border bg-elevated p-5">
              <div className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">Install command</div>
              <pre className="overflow-x-auto rounded-md bg-background p-3 text-xs font-mono text-foreground">
                <code>{`npx @bayn/mcp install --target=claude --token=YOUR_TOKEN`}</code>
              </pre>
              <p className="mt-2 text-[11px] text-muted-foreground">
                Or skip — you can connect from Settings → Agent anytime.
              </p>
            </div>
          </Step>
        )}

        {step === 6 && (
          <Step title="Pick a plan"
            sub={path === "developer"
              ? "Studio is paid only. Pick a tier to enter the builder."
              : "Your 4 free verified strategies are already active. Upgrade to unlock premium catalog strategies and the full agentic loop."}>
            <div className="mb-6 flex justify-center">
              <BillingToggle value={billing} onChange={setBilling}
                accent={path === "developer" ? "violet" : "cyan"} />
            </div>
            <PricingTable
              audience={path === "developer" ? "developer" : "trader"}
              billing={billing}
              onSelect={(id: TierId) => {
                if (id.startsWith("studio")) setCurrentPlan({ developer: id, billing });
                else setCurrentPlan({ trader: id, billing });
                toast.success("Plan selected");
                next();
              }}
            />
            {path !== "developer" && (
              <div className="mt-8 rounded-xl border border-border bg-elevated p-4 text-center">
                <Button variant="ghost" onClick={() => { setCurrentPlan({ trader: null }); next(); }}>
                  Continue on Free — keep my 4 verified strategies
                </Button>
              </div>
            )}
          </Step>
        )}

        {step === 7 && (path === "developer" || path === "both") && (
          <Step title="The Studio loop"
            sub="Three-step build cycle. The same workflow institutional research desks run — operated by you alone.">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <StudioStep icon={Wand2} title="Describe" body="Tell the AI co-builder what edge you want. It places the right nodes on the canvas." />
              <StudioStep icon={Workflow} title="Build" body="Refine the graph. Wire indicators, filters, risk and execution nodes." />
              <StudioStep icon={BarChart3} title="Backtest & deploy" body="Walk-forward, Monte Carlo, then forward-test live for your own signal feed." />
            </div>
            <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-2">
              <Button asChild className="h-11" style={{ background: "var(--violet)", color: "var(--violet-foreground)" }}>
                <Link to="/studio/builder/$id" params={{ id: "new" }}>Describe a first strategy <ArrowRight className="ml-1.5 size-4" /></Link>
              </Button>
              <Button asChild variant="outline" className="h-11">
                <Link to="/studio/strategies">Start from a template</Link>
              </Button>
            </div>
          </Step>
        )}

        {step === 7 && path === "trader" && <LandingChecklist mode="trader" onFinish={finish} />}
        {step === 8 && <LandingChecklist mode={path === "developer" ? "developer" : "trader"} onFinish={finish} />}

        {/* Nav */}
        <div className="mt-10 flex items-center justify-between">
          <Button variant="ghost" onClick={back} disabled={step === 1}>
            <ArrowLeft className="size-4" /> Back
          </Button>
          {step < totalSteps ? (
            <Button onClick={next} className="text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}>
              Continue <ArrowRight className="ml-1.5 size-4" />
            </Button>
          ) : (
            <Button onClick={finish} className="text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}>
              Enter Bayn <ArrowRight className="ml-1.5 size-4" />
            </Button>
          )}
        </div>
      </main>
    </div>
  );
}

/* ---------------- Sub-components ---------------- */

function ProgressBar({ step, total }: { step: number; total: number }) {
  const pct = Math.round((step / total) * 100);
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-elevated">
      <div className="h-full transition-all duration-300" style={{ width: `${pct}%`, background: "var(--gradient-emerald)" }} />
    </div>
  );
}

function Step({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section>
      <h1 className="text-3xl font-bold leading-tight md:text-4xl"
        style={{ fontFamily: "var(--font-landing-display)", letterSpacing: "-0.02em" }}>
        {title}
      </h1>
      {sub && <p className="mt-2 max-w-2xl text-sm text-muted-foreground md:text-base">{sub}</p>}
      <div className="mt-8">{children}</div>
    </section>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <Label className="text-xs uppercase tracking-wider text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function PathCard({
  icon: Icon, title, sub, accent, active, onClick,
}: {
  icon: typeof Sparkles; title: string; sub: string;
  accent: "cyan" | "violet" | "emerald"; active: boolean; onClick: () => void;
}) {
  const c = accent === "violet" ? "var(--violet)" : accent === "cyan" ? "var(--cyan)" : "var(--emerald-glow)";
  return (
    <button onClick={onClick}
      className={cn(
        "flex flex-col items-start gap-3 rounded-2xl border p-6 text-left transition-all",
        active ? "scale-[1.01]" : "hover:border-foreground/30",
      )}
      style={{
        background: active ? `linear-gradient(135deg, color-mix(in oklab, ${c} 14%, var(--elevated)), var(--elevated))` : "var(--elevated)",
        borderColor: active ? c : "var(--border)",
        boxShadow: active ? `0 20px 40px -20px color-mix(in oklab, ${c} 50%, transparent)` : undefined,
      }}>
      <div className="grid size-10 place-items-center rounded-xl"
        style={{ background: `color-mix(in oklab, ${c} 18%, transparent)`, color: c }}>
        <Icon className="size-5" />
      </div>
      <div>
        <h3 className="text-base font-semibold">{title}</h3>
        <p className="mt-1 text-xs text-muted-foreground">{sub}</p>
      </div>
    </button>
  );
}

function FreeStrategyActivation({ assets }: { assets: Asset[] }) {
  const map: Record<Asset, { name: string; sharpe: number }> = {
    stocks: { name: "Mean Reversion — SPY 2-Day", sharpe: 1.08 },
    crypto: { name: "Mean Reversion — BTC Hourly", sharpe: 1.64 },
    options: { name: "Far-OTM Weekly Premium — SPY", sharpe: 1.36 },
    futures: { name: "MES Opening Range Reversal", sharpe: 1.27 },
  };
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {assets.map((a, i) => {
        const s = map[a];
        return (
          <div key={a}
            className="relative overflow-hidden rounded-xl border p-4"
            style={{
              borderColor: "color-mix(in oklab, var(--brand-gold) 30%, var(--border))",
              background: "linear-gradient(135deg, color-mix(in oklab, var(--brand-gold) 8%, var(--elevated)), var(--elevated))",
              animation: `mode-fade 400ms ease-out ${i * 80}ms both`,
            }}>
            <div className="mb-2 flex items-center justify-between">
              <span className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider"
                style={{ background: "color-mix(in oklab, var(--brand-gold) 18%, transparent)", color: "var(--brand-gold)" }}>
                <BadgeCheck className="size-3" /> Free · Verified
              </span>
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{a}</span>
            </div>
            <div className="text-sm font-medium">{s.name}</div>
            <div className="mt-1 text-xs text-muted-foreground">Sharpe {s.sharpe} · live tracked</div>
            <div className="mt-3 inline-flex items-center gap-1 text-xs" style={{ color: "var(--emerald-glow)" }}>
              <Check className="size-3.5" /> Activated
            </div>
          </div>
        );
      })}
    </div>
  );
}

function AgentLoopDiagram() {
  const node = (label: string, sub: string, icon: typeof Bot) => {
    const Icon = icon;
    return (
      <div className="flex items-center gap-3 rounded-xl border border-border bg-elevated px-4 py-3">
        <div className="grid size-9 place-items-center rounded-lg" style={{ background: "color-mix(in oklab, var(--emerald) 18%, transparent)", color: "var(--emerald-glow)" }}>
          <Icon className="size-4" />
        </div>
        <div>
          <div className="text-sm font-medium">{label}</div>
          <div className="text-[11px] text-muted-foreground">{sub}</div>
        </div>
      </div>
    );
  };
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3 md:items-center">
      {node("Signal fires", "Verified strategy emits trade", LineChart)}
      <div className="hidden md:flex md:justify-center"><ArrowRight className="size-4 text-muted-foreground" /></div>
      {node("Your AI agent", "Bayn MCP + Claude/GPT", Bot)}
      <div className="hidden md:flex md:justify-center"><ArrowRight className="size-4 text-muted-foreground" /></div>
      {node("Broker", "Robinhood Agentic confirms", Zap)}
    </div>
  );
}

function StudioStep({ icon: Icon, title, body }: { icon: typeof Wand2; title: string; body: string }) {
  return (
    <div className="rounded-xl border border-border bg-elevated p-5">
      <div className="grid size-9 place-items-center rounded-lg" style={{ background: "color-mix(in oklab, var(--violet) 18%, transparent)", color: "var(--violet)" }}>
        <Icon className="size-4" />
      </div>
      <h4 className="mt-3 text-sm font-semibold">{title}</h4>
      <p className="mt-1 text-xs text-muted-foreground">{body}</p>
    </div>
  );
}

function LandingChecklist({ mode, onFinish }: { mode: "trader" | "developer"; onFinish: () => void }) {
  const items = mode === "trader"
    ? ["Subscribe to your first premium strategy", "Connect an agent or broker", "Take your first signal"]
    : ["Build your first strategy in the node editor", "Run your first backtest", "Deploy a strategy to forward-test"];
  const accent = mode === "developer" ? "var(--violet)" : "var(--cyan)";
  return (
    <Step title="You're in" sub="A short checklist to get the loop running. You can come back to these anytime.">
      <ul className="space-y-2.5">
        {items.map((t) => (
          <li key={t} className="flex items-center gap-3 rounded-xl border border-border bg-elevated p-4">
            <span className="grid size-6 place-items-center rounded-full border border-border text-xs text-muted-foreground">○</span>
            <span className="text-sm">{t}</span>
          </li>
        ))}
      </ul>
      <Button onClick={onFinish}
        className="mt-6 h-11 w-full md:w-auto"
        style={{ background: accent, color: "var(--background)" }}>
        Open my {mode === "developer" ? "Studio" : "feed"} <ArrowRight className="ml-1.5 size-4" />
      </Button>
    </Step>
  );
}
