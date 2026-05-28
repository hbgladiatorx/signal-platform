import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import {
  ArrowRight, ArrowLeft, Sparkles, BadgeCheck, Layers, Loader2,
  ShieldCheck, X, Check, Plus, LogOut,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { PricingTable } from "@/components/billing/PricingTable";
import { getCurrentPlan, setBillingScope, setCurrentPlan, type Billing, type TierId } from "@/lib/api/billing";
import { validateTicker } from "@/lib/api/finnhub.functions";
import {
  setTraderSeeded, setStudioSeeded, setOnboarded,
  setEnabledAssetClasses, setOnboardingPath,
  setAccountSize as persistAccountSize, setRiskPerTrade, setPreferenceScope,
  useWatchlist, useIdentity, useExperienceProfile,
  useNewsSources, useNewsCategories, useOnlyNewsForWatched,
  useMaxConcurrentPositions, useDailyLossLimit,
  useBrokerConnections, useAgentSetup, useNotifications,
  useStudioAssetClasses, useStudioExperience, useBacktestDefaults,
  useForwardTestDefaults, useStudioAiPreferences, useStudioWorkspaceDefaults,
  usePayoutPreference, useDefaultModeOnLogin, setOnboardingResume,

  type BrokerId, type AgentPlatform,
  type BuilderEntry, type StudioExperience, type NodeStyle,
} from "@/lib/user-prefs";
import type { AssetClass as AC } from "@/lib/types";


export const Route = createFileRoute("/onboarding")({
  head: () => ({ meta: [{ title: "Welcome to Bayn" }] }),
  component: OnboardingPage,
});

type Path = "trader" | "developer" | "both";

const ASSETS: { key: AC; label: string }[] = [
  { key: "stocks", label: "Stocks" },
  { key: "crypto", label: "Crypto" },
  { key: "options", label: "Options" },
  { key: "futures", label: "Futures" },
];

const SUGGESTED_TICKERS: Record<AC, string[]> = {
  stocks: ["SPY", "QQQ", "AAPL", "NVDA", "MSFT", "AMZN", "TSLA"],
  crypto: ["BINANCE:BTCUSDT", "BINANCE:ETHUSDT", "BINANCE:SOLUSDT"],
  options: ["SPY", "QQQ", "AAPL"],
  futures: ["ES1!", "NQ1!", "CL1!"],
};

const TOPICS = ["Earnings", "Macro", "Crypto", "Options Flow", "M&A", "Fed", "Geopolitics"];
const BROKERS: { id: BrokerId; name: string }[] = [
  { id: "coinbase", name: "Coinbase" }, { id: "ibkr", name: "Interactive Brokers" },
  { id: "tradier", name: "Tradier" }, { id: "topstepx", name: "TopstepX" },
  { id: "robinhood-agentic", name: "Robinhood Agentic" },
];
const AGENT_PLATFORMS: { id: AgentPlatform; name: string }[] = [
  { id: "claude-code", name: "Claude Code" }, { id: "claude-desktop", name: "Claude Desktop" },
  { id: "chatgpt", name: "ChatGPT" }, { id: "codex", name: "Codex" },
  { id: "cursor", name: "Cursor" }, { id: "other", name: "Other" },
];

function OnboardingPage() {
  const nav = useNavigate();
  const [authChecked, setAuthChecked] = useState(false);
  const [path, setPath] = useState<Path>("trader");
  const [step, setStep] = useState(0);
  const [billing, setBilling] = useState<Billing>("annual");

  // Auth bootstrap
  useEffect(() => {
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      if (!data.session) { nav({ to: "/auth" }); return; }
      setPreferenceScope(data.session.user.id);
      setBillingScope(data.session.user.id);
      const email = data.session.user.email ?? "";
      // Seed identity defaults if blank
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      // Identity write happens on save in identity step
      void email; void tz;
      setAuthChecked(true);
    });
    return () => { active = false; };
  }, [nav]);

  const steps = useMemo(() => buildSteps(path), [path]);
  const total = steps.length;
  const current = steps[step];

  // Persist resume position
  useEffect(() => { setOnboardingResume({ step, total }); }, [step, total]);

  const next = () => setStep((s) => Math.min(s + 1, total - 1));
  const back = () => setStep((s) => Math.max(s - 1, 0));

  const finishAndExit = (markComplete: boolean) => {
    setOnboardingPath(path);
    if (path === "trader" || path === "both") setTraderSeeded(true);
    if (path === "developer" || path === "both") setStudioSeeded(true);
    if (markComplete) {
      setOnboarded(true);
      setOnboardingResume(null);
    } else {
      setOnboarded(true); // allow access; checklist surfaces remaining items
    }
    const plan = getCurrentPlan();
    if (path === "developer") {
      nav({ to: plan.developer ? "/studio/home" : "/studio/pricing" });
    } else {
      nav({ to: "/app/home" });
    }
  };

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
          <Button variant="ghost" size="sm" onClick={() => finishAndExit(false)}>
            <LogOut className="mr-1.5 size-3.5" /> Save &amp; exit
          </Button>
        </div>
        <div className="mx-auto max-w-5xl px-6 pb-4 md:px-10">
          <ProgressBar step={step + 1} total={total} />
          <div className="mt-2 flex items-center justify-between text-[11px] uppercase tracking-wider text-muted-foreground">
            <span>Step {step + 1} of {total}</span>
            <span>{current.label}</span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-10 md:px-10 md:py-12">
        {current.key === "path" && <StepPath path={path} setPath={setPath} />}
        {current.key === "identity" && <StepIdentity />}
        {current.key === "experience" && <StepExperience />}
        {current.key === "markets" && <StepMarkets />}
        {current.key === "tickers" && <StepTickers />}
        {current.key === "news" && <StepNews />}
        {current.key === "risk" && <StepRisk />}
        {current.key === "brokers" && <StepBrokers />}
        {current.key === "agent" && <StepAgent />}
        {current.key === "notifications" && <StepNotifications />}
        {current.key === "plan" && <StepPlan billing={billing} setBilling={setBilling} audience="trader" onPick={next} />}
        {current.key === "studioMarkets" && <StepStudioMarkets />}
        {current.key === "builderExp" && <StepBuilderExp />}
        {current.key === "backtestDefaults" && <StepBacktestDefaults />}
        {current.key === "forwardTest" && <StepForwardTest />}
        {current.key === "studioAi" && <StepStudioAi />}
        {current.key === "studioPlan" && <StepPlan billing={billing} setBilling={setBilling} audience="developer" onPick={next} />}
        {current.key === "payout" && <StepPayout />}
        {current.key === "workspace" && <StepWorkspace />}
        {current.key === "firstStrategy" && <StepFirstStrategy />}
        {current.key === "defaultMode" && <StepDefaultMode />}
        {current.key === "done" && <StepDone path={path} />}

        <div className="mt-10 flex items-center justify-between">
          <Button variant="ghost" onClick={back} disabled={step === 0}>
            <ArrowLeft className="mr-1.5 size-4" /> Back
          </Button>
          {step < total - 1 ? (
            <Button onClick={next} className="text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}>
              Continue <ArrowRight className="ml-1.5 size-4" />
            </Button>
          ) : (
            <Button onClick={() => finishAndExit(true)} className="text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}>
              Enter Bayn <ArrowRight className="ml-1.5 size-4" />
            </Button>
          )}
        </div>
      </main>
    </div>
  );
}

/* ---------------- Step graph ---------------- */

type StepKey =
  | "path" | "identity" | "experience"
  | "markets" | "tickers" | "news" | "risk" | "brokers" | "agent" | "notifications" | "plan"
  | "studioMarkets" | "builderExp" | "backtestDefaults" | "forwardTest" | "studioAi"
  | "studioPlan" | "payout" | "workspace" | "firstStrategy" | "defaultMode" | "done";

function buildSteps(path: Path): { key: StepKey; label: string }[] {
  const shared: { key: StepKey; label: string }[] = [
    { key: "path", label: "Choose your path" },
    { key: "identity", label: "Identity" },
    { key: "experience", label: "Experience profile" },
  ];
  const trader: { key: StepKey; label: string }[] = [
    { key: "markets", label: "Markets you trade" },
    { key: "tickers", label: "Watched tickers" },
    { key: "news", label: "News sources" },
    { key: "risk", label: "Risk &amp; sizing" },
    { key: "brokers", label: "Broker connections" },
    { key: "agent", label: "AI agent" },
    { key: "notifications", label: "Notifications" },
    { key: "plan", label: "Plan" },
  ];
  const studio: { key: StepKey; label: string }[] = [
    { key: "studioMarkets", label: "Build for which markets" },
    { key: "builderExp", label: "Builder experience" },
    { key: "backtestDefaults", label: "Backtest defaults" },
    { key: "forwardTest", label: "Forward-test defaults" },
    { key: "studioAi", label: "Studio AI" },
    { key: "studioPlan", label: "Studio plan" },
    { key: "payout", label: "Payout (optional)" },
    { key: "workspace", label: "Workspace defaults" },
    { key: "firstStrategy", label: "First strategy" },
  ];
  const studioCondensed: { key: StepKey; label: string }[] = [
    { key: "studioMarkets", label: "Build for which markets" },
    { key: "builderExp", label: "Builder experience" },
    { key: "studioAi", label: "Studio AI" },
    { key: "studioPlan", label: "Studio plan" },
    { key: "firstStrategy", label: "First strategy" },
    { key: "defaultMode", label: "Default landing surface" },
  ];

  if (path === "trader") return [...shared, ...trader, { key: "done", label: "Finish" }];
  if (path === "developer") return [...shared, ...studio, { key: "done", label: "Finish" }];
  return [...shared, ...trader, ...studioCondensed, { key: "done", label: "Finish" }];
}

/* ---------------- Step components ---------------- */

function StepPath({ path, setPath }: { path: Path; setPath: (p: Path) => void }) {
  return (
    <Step title="Trader, Studio, or Both?" sub="Choose where you'll start. We tailor the rest of setup to your choice.">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <PathCard active={path === "trader"} onClick={() => setPath("trader")} icon={BadgeCheck} accent="cyan"
          title="Trader" sub="Follow verified strategies and act on live signals." />
        <PathCard active={path === "developer"} onClick={() => setPath("developer")} icon={Layers} accent="violet"
          title="Studio" sub="Build, backtest, and publish your own strategies." />
        <PathCard active={path === "both"} onClick={() => setPath("both")} icon={Sparkles} accent="emerald"
          title="Both" sub="Get the trader dashboard plus the Studio builder." />
      </div>
    </Step>
  );
}

function StepIdentity() {
  const [identity, setIdent] = useIdentity();
  useEffect(() => {
    if (!identity.timezone) {
      setIdent({ ...identity, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <Step title="Tell us who you are" sub="Used across the app for display and timing. You can change these in Settings later.">
      <div className="space-y-5">
        <Group label="Display name">
          <Input value={identity.displayName} maxLength={60}
            onChange={(e) => setIdent({ ...identity, displayName: e.target.value })}
            placeholder="What should we call you?" className="h-11 bg-elevated" />
        </Group>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Group label="Timezone">
            <Input value={identity.timezone}
              onChange={(e) => setIdent({ ...identity, timezone: e.target.value })}
              className="h-11 bg-elevated" />
          </Group>
          <Group label="Currency">
            <select value={identity.currency}
              onChange={(e) => setIdent({ ...identity, currency: e.target.value })}
              className="h-11 w-full rounded-md border border-input bg-elevated px-3 text-sm">
              {["USD", "EUR", "GBP", "CAD", "AUD", "JPY"].map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </Group>
        </div>
      </div>
    </Step>
  );
}

function StepExperience() {
  const [exp, setExp] = useExperienceProfile();
  const levels = ["retail", "active", "professional", "institutional"] as const;
  const years = ["<1", "1-3", "3-5", "5-10", "10+"];
  const motivations = ["consistent income", "growth", "learning", "automation", "replacing a manual process"];
  const sources = ["solo research", "paid services", "social", "none yet"];
  return (
    <Step title="Your experience" sub="Drives recommendations and onboarding copy. Nothing here is binding.">
      <div className="space-y-6">
        <Group label="Self-reported level">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {levels.map((l) => (
              <Chip key={l} on={exp.level === l} onClick={() => setExp({ ...exp, level: l })}>{l}</Chip>
            ))}
          </div>
        </Group>
        <Group label="Years actively trading">
          <div className="flex flex-wrap gap-2">
            {years.map((y) => (
              <Chip key={y} on={exp.years === y} onClick={() => setExp({ ...exp, years: y })}>{y}</Chip>
            ))}
          </div>
        </Group>
        <Group label="Primary motivations (multi-select)">
          <div className="flex flex-wrap gap-2">
            {motivations.map((m) => (
              <Chip key={m} on={exp.motivations.includes(m)}
                onClick={() => setExp({ ...exp, motivations: toggle(exp.motivations, m) })}>{m}</Chip>
            ))}
          </div>
        </Group>
        <Group label="How you get ideas today">
          <div className="flex flex-wrap gap-2">
            {sources.map((s) => (
              <Chip key={s} on={exp.signalSources.includes(s)}
                onClick={() => setExp({ ...exp, signalSources: toggle(exp.signalSources, s) })}>{s}</Chip>
            ))}
          </div>
        </Group>
      </div>
    </Step>
  );
}

function StepMarkets() {
  const [classes, setClasses] = useState<AC[]>([]);
  useEffect(() => {
    // load from prefs
    const stored = (typeof window !== "undefined" ? window.localStorage.getItem("") : null);
    void stored;
  }, []);
  // We keep classes locally and write through both setEnabledAssetClasses + studio prefs
  return (
    <Step title="Which markets do you trade?" sub="Cascades through every filter. Pick at least one to enable live data.">
      <div className="flex flex-wrap gap-2">
        {ASSETS.map((a) => {
          const on = classes.includes(a.key);
          return (
            <Chip key={a.key} on={on}
              onClick={() => {
                const next = on ? classes.filter((x) => x !== a.key) : [...classes, a.key];
                setClasses(next);
                setEnabledAssetClasses(next);
              }}>{a.label}</Chip>
          );
        })}
      </div>
      {classes.length === 0 && (
        <p className="mt-4 text-xs text-muted-foreground">Tip: you can change this any time in Customize.</p>
      )}
    </Step>
  );
}

function StepTickers() {
  const [watch, setWatch] = useWatchlist();
  const [pending, setPending] = useState("");
  const [busy, setBusy] = useState(false);
  const validate = useServerFn(validateTicker);

  const add = async (sym: string) => {
    const s = sym.trim().toUpperCase();
    if (!s || watch.includes(s)) return;
    setBusy(true);
    try {
      const info = await validate({ data: { symbol: s } });
      if (!info.valid) { toast.error(`"${s}" is not a recognized ticker`); return; }
      setWatch([...watch, info.symbol]);
      setPending("");
      toast.success(`${info.symbol} added${info.description ? ` — ${info.description}` : ""}`);
    } catch {
      toast.error("Could not validate ticker right now");
    } finally { setBusy(false); }
  };

  const remove = (s: string) => setWatch(watch.filter((x) => x !== s));
  const suggested = Array.from(new Set(Object.values(SUGGESTED_TICKERS).flat())).filter((s) => !watch.includes(s));

  return (
    <Step title="Watched tickers" sub="Live quotes and news come from Finnhub. Type any symbol — we validate it.">
      <div className="flex gap-2">
        <Input value={pending} onChange={(e) => setPending(e.target.value.toUpperCase())}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(pending); } }}
          placeholder="e.g. AAPL, BINANCE:BTCUSDT" className="h-11 bg-elevated" />
        <Button onClick={() => add(pending)} disabled={busy || !pending.trim()}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
        </Button>
      </div>
      {watch.length > 0 && (
        <div className="mt-4">
          <Label className="text-xs uppercase tracking-wider text-muted-foreground">Your watchlist</Label>
          <div className="mt-2 flex flex-wrap gap-2">
            {watch.map((s) => (
              <span key={s} className="inline-flex items-center gap-1.5 rounded-full border border-cyan/40 bg-cyan/10 px-3 py-1 font-mono text-xs text-cyan">
                {s}
                <button onClick={() => remove(s)} className="opacity-70 hover:opacity-100"><X className="size-3" /></button>
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="mt-6">
        <Label className="text-xs uppercase tracking-wider text-muted-foreground">Quick add</Label>
        <div className="mt-2 flex flex-wrap gap-2">
          {suggested.slice(0, 12).map((s) => (
            <button key={s} onClick={() => add(s)}
              className="rounded-full border border-border bg-elevated px-3 py-1 font-mono text-xs text-muted-foreground hover:text-foreground">
              + {s}
            </button>
          ))}
        </div>
      </div>
    </Step>
  );
}

function StepNews() {
  const [sources, setSources] = useNewsSources();
  const [topics, setTopics] = useNewsCategories();
  const [onlyWatched, setOnlyWatched] = useOnlyNewsForWatched();
  return (
    <Step title="News &amp; topics" sub="Market Wire stays empty until you turn things on here.">
      <div className="space-y-6">
        <Group label="Sources">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {sources.map((s) => (
              <button key={s.id} onClick={() => setSources(sources.map((x) => x.id === s.id ? { ...x, enabled: !x.enabled } : x))}
                className={cn("flex items-center justify-between rounded-lg border px-3 py-2 text-sm transition-colors",
                  s.enabled ? "border-cyan/50 bg-cyan/10 text-cyan" : "border-border bg-elevated text-muted-foreground hover:text-foreground")}>
                <span>{s.name}</span>
                {s.enabled && <Check className="size-3.5" />}
              </button>
            ))}
          </div>
        </Group>
        <Group label="Topic filters">
          <div className="flex flex-wrap gap-2">
            {TOPICS.map((t) => (
              <Chip key={t} on={(topics as readonly string[]).includes(t as never)}
                onClick={() => setTopics(toggle(topics as string[], t) as never)}>{t}</Chip>
            ))}
          </div>
        </Group>
        <div className="flex items-center justify-between rounded-lg border border-border bg-elevated p-3">
          <div>
            <Label className="text-sm">Only show news for my watched tickers</Label>
            <p className="text-xs text-muted-foreground">Filters Market Wire to symbols on your watchlist.</p>
          </div>
          <Switch checked={onlyWatched} onCheckedChange={setOnlyWatched} />
        </div>
      </div>
    </Step>
  );
}

function StepRisk() {
  const [accountSize, setAcct] = useState<string>("");
  const [riskPct, setRisk] = useState<string>("1");
  const [maxConc, setMaxConc] = useMaxConcurrentPositions();
  const [loss, setLoss] = useDailyLossLimit();

  // commit on blur via small effect-free handlers
  const commit = () => {
    persistAccountSize(Number(accountSize) || 0);
    setRiskPerTrade((Number(riskPct) || 0) / 100);
  };

  return (
    <Step title="Risk &amp; position sizing" sub="Bayn never trades for you — these drive suggested size on every signal.">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Group label="Account size (USD)">
          <Input value={accountSize} onChange={(e) => setAcct(e.target.value.replace(/[^0-9]/g, ""))}
            onBlur={commit} inputMode="numeric" className="h-11 bg-elevated" placeholder="25000" />
        </Group>
        <Group label="Default risk per trade (%)">
          <Input value={riskPct} onChange={(e) => setRisk(e.target.value.replace(/[^0-9.]/g, ""))}
            onBlur={commit} inputMode="decimal" className="h-11 bg-elevated" />
        </Group>
        <Group label={`Max concurrent positions: ${maxConc}`}>
          <Slider value={[maxConc]} min={1} max={20} step={1} onValueChange={(v) => setMaxConc(v[0])} />
        </Group>
        <div className="rounded-lg border border-border bg-elevated p-3">
          <div className="flex items-center justify-between">
            <Label className="text-sm">Daily loss limit</Label>
            <Switch checked={loss.enabled} onCheckedChange={(v) => setLoss({ ...loss, enabled: v })} />
          </div>
          {loss.enabled && (
            <Input type="number" value={loss.threshold || ""} onChange={(e) => setLoss({ ...loss, threshold: Number(e.target.value) || 0 })}
              placeholder="Stop trading after USD loss" className="mt-2 h-10 bg-background" />
          )}
        </div>
      </div>
      <div className="mt-5 flex items-start gap-2 rounded-lg border border-border bg-elevated p-3 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" style={{ color: "var(--emerald-glow)" }} />
        Suggestions only. You always execute.
      </div>
    </Step>
  );
}

function StepBrokers() {
  const [connections, setConn] = useBrokerConnections();
  return (
    <Step title="Broker connections" sub="Optional. Connect now or skip — broker integrations land soon.">
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {BROKERS.map((b) => {
          const on = connections.includes(b.id);
          return (
            <button key={b.id} onClick={() => setConn(on ? connections.filter((x) => x !== b.id) : [...connections, b.id])}
              className={cn("flex items-center justify-between rounded-lg border px-4 py-3 text-sm transition-colors",
                on ? "border-cyan/50 bg-cyan/10 text-cyan" : "border-border bg-elevated text-muted-foreground hover:text-foreground")}>
              <span>{b.name}</span>
              <span className="text-[10px] uppercase tracking-wider">{on ? "Marked" : "Coming soon"}</span>
            </button>
          );
        })}
      </div>
      <p className="mt-4 text-xs text-muted-foreground">We save your preference now and surface the connect flow once it ships.</p>
    </Step>
  );
}

function StepAgent() {
  const [agent, setAgent] = useAgentSetup();
  return (
    <Step title="AI agent setup" sub="Pick the platform you'll use Bayn's MCP from. Skippable.">
      <Group label="Platform">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
          {AGENT_PLATFORMS.map((p) => (
            <Chip key={p.id} on={agent.platform === p.id} onClick={() => setAgent({ ...agent, platform: p.id })}>
              {p.name}
            </Chip>
          ))}
        </div>
      </Group>
      <div className="mt-5 space-y-3">
        <RowToggle label="Bayn MCP installed" desc="Mark when you've added the Bayn MCP to your agent."
          on={agent.baynMcpConnected} onChange={(v) => setAgent({ ...agent, baynMcpConnected: v })} />
        <RowToggle label="Allow agent to read my signal feed" desc="Your agent can query live signals."
          on={agent.readSignalFeed} onChange={(v) => setAgent({ ...agent, readSignalFeed: v })} />
        <RowToggle label="Brokerage agent connected" desc="A brokerage-side agent can place orders for you."
          on={agent.brokerageAgentConnected} onChange={(v) => setAgent({ ...agent, brokerageAgentConnected: v })} />
      </div>
    </Step>
  );
}

function StepNotifications() {
  const [notifs, setNotifs] = useNotifications();
  const items: { key: keyof typeof notifs; label: string }[] = [
    { key: "signalFired", label: "New signal fired" },
    { key: "signalHitTarget", label: "Signal hit target" },
    { key: "signalHitStop", label: "Signal hit stop" },
    { key: "weeklySummary", label: "Weekly performance summary" },
    { key: "strategyHWM", label: "Strategy new high-water mark" },
    { key: "tickerNews", label: "News for watched tickers" },
  ];
  return (
    <Step title="Notifications" sub="Sensible defaults pre-checked. Email/SMS delivery coming soon — your toggles are saved.">
      <div className="space-y-2">
        {items.map((it) => (
          <RowToggle key={it.key as string} label={it.label}
            on={notifs[it.key]} onChange={(v) => setNotifs({ ...notifs, [it.key]: v })} />
        ))}
      </div>
    </Step>
  );
}

function StepPlan({ billing, setBilling, audience, onPick }: {
  billing: Billing; setBilling: (v: Billing) => void;
  audience: "trader" | "developer"; onPick: () => void;
}) {
  return (
    <Step title={audience === "developer" ? "Studio plan" : "Trader plan"}
      sub={audience === "developer"
        ? "Studio is only visible with a Studio plan. Pick one or compare later."
        : "Stay on Free (4 verified strategies) or upgrade for the premium catalog."}>
      <div className="mb-6 flex justify-center rounded-full border border-border bg-elevated p-1">
        {(["annual", "monthly"] as Billing[]).map((b) => (
          <button key={b} onClick={() => setBilling(b)}
            className={cn("rounded-full px-4 py-1.5 text-xs font-medium capitalize transition-colors",
              billing === b ? "bg-cyan text-cyan-foreground" : "text-muted-foreground hover:text-foreground")}>
            {b}
          </button>
        ))}
      </div>
      <PricingTable audience={audience} billing={billing} onSelect={(id: TierId) => {
        setCurrentPlan(audience === "developer" ? { developer: id, billing } : { trader: id, billing });
        toast.success("Plan selected");
        onPick();
      }} />
      <div className="mt-6 text-center">
        <Button variant="ghost" onClick={onPick}>
          {audience === "developer" ? "Compare Studio plans later" : "Stay on Free for now"}
        </Button>
      </div>
    </Step>
  );
}

function StepStudioMarkets() {
  const [classes, setClasses] = useStudioAssetClasses();
  return (
    <Step title="Which markets will you build for?" sub="Drives default symbols and data availability in the builder.">
      <div className="flex flex-wrap gap-2">
        {ASSETS.map((a) => (
          <Chip key={a.key} on={classes.includes(a.key)}
            onClick={() => setClasses(toggle(classes, a.key))}>{a.label}</Chip>
        ))}
      </div>
    </Step>
  );
}

function StepBuilderExp() {
  const [exp, setExp] = useStudioExperience();
  const levels: StudioExperience[] = ["none", "some", "strong", "professional"];
  const entries: { key: BuilderEntry; label: string; desc: string }[] = [
    { key: "template", label: "Start from a template", desc: "Pick a verified template to fork." },
    { key: "ai-describe", label: "Describe to AI", desc: "Tell the AI co-builder what you want." },
    { key: "blank", label: "Blank canvas", desc: "Drop nodes manually." },
  ];
  return (
    <Step title="Builder experience" sub="We'll calibrate the walkthrough.">
      <div className="space-y-6">
        <Group label="Quant / coding experience">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {levels.map((l) => (
              <Chip key={l} on={exp.level === l} onClick={() => setExp({ ...exp, level: l })}>{l}</Chip>
            ))}
          </div>
        </Group>
        <Group label="Used a node-based builder before?">
          <div className="flex gap-2">
            <Chip on={exp.usedNodeBuilder === true} onClick={() => setExp({ ...exp, usedNodeBuilder: true })}>Yes</Chip>
            <Chip on={exp.usedNodeBuilder === false} onClick={() => setExp({ ...exp, usedNodeBuilder: false })}>No</Chip>
          </div>
        </Group>
        <Group label="Preferred starting point">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            {entries.map((e) => (
              <button key={e.key} onClick={() => setExp({ ...exp, entry: e.key })}
                className={cn("rounded-lg border p-3 text-left transition-colors",
                  exp.entry === e.key ? "border-violet/50 bg-violet/10" : "border-border bg-elevated hover:border-foreground/30")}>
                <div className="text-sm font-semibold">{e.label}</div>
                <div className="mt-1 text-xs text-muted-foreground">{e.desc}</div>
              </button>
            ))}
          </div>
        </Group>
      </div>
    </Step>
  );
}

function StepBacktestDefaults() {
  const [bt, setBt] = useBacktestDefaults();
  return (
    <Step title="Backtest defaults" sub="Pre-fill every new backtest run. Override per strategy later.">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Group label="Starting capital (USD)">
          <Input type="number" value={bt.startingCapital || ""} onChange={(e) => setBt({ ...bt, startingCapital: Number(e.target.value) || 0 })}
            className="h-11 bg-elevated" />
        </Group>
        <Group label="Date range">
          <div className="flex gap-2">
            {(["1Y", "3Y", "5Y", "MAX"] as const).map((r) => (
              <Chip key={r} on={bt.dateRange === r} onClick={() => setBt({ ...bt, dateRange: r })}>{r}</Chip>
            ))}
          </div>
        </Group>
        <Group label="Commission model">
          <select value={bt.commissionModel}
            onChange={(e) => setBt({ ...bt, commissionModel: e.target.value as typeof bt.commissionModel })}
            className="h-11 w-full rounded-md border border-input bg-elevated px-3 text-sm">
            <option value="per-share">Per share</option>
            <option value="per-contract">Per contract</option>
            <option value="percent">Percent</option>
            <option value="custom">Custom</option>
          </select>
        </Group>
        <Group label="Slippage (bps)">
          <Input type="number" value={bt.slippageBps || ""} onChange={(e) => setBt({ ...bt, slippageBps: Number(e.target.value) || 0 })}
            className="h-11 bg-elevated" />
        </Group>
      </div>
    </Step>
  );
}

function StepForwardTest() {
  const [ft, setFt] = useForwardTestDefaults();
  return (
    <Step title="Forward-test defaults" sub="Used when you promote a backtest to live paper.">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Group label="Paper capital (USD)">
          <Input type="number" value={ft.paperCapital || ""} onChange={(e) => setFt({ ...ft, paperCapital: Number(e.target.value) || 0 })}
            className="h-11 bg-elevated" />
        </Group>
        <Group label={`Auto-promote after ${ft.autoPromoteDays} passing days`}>
          <Slider value={[ft.autoPromoteDays]} min={7} max={90} step={1} onValueChange={(v) => setFt({ ...ft, autoPromoteDays: v[0] })} />
        </Group>
      </div>
      <div className="mt-4 space-y-2">
        <Label className="text-xs uppercase tracking-wider text-muted-foreground">Personal signal delivery</Label>
        <RowToggle label="In-app" on={ft.delivery.inApp} onChange={(v) => setFt({ ...ft, delivery: { ...ft.delivery, inApp: v } })} />
        <RowToggle label="Email" on={ft.delivery.email} onChange={(v) => setFt({ ...ft, delivery: { ...ft.delivery, email: v } })} />
        <RowToggle label="Push" on={ft.delivery.push} onChange={(v) => setFt({ ...ft, delivery: { ...ft.delivery, push: v } })} />
      </div>
    </Step>
  );
}

function StepStudioAi() {
  const [ai, setAi] = useStudioAiPreferences();
  const styles: { key: NodeStyle; label: string; desc: string }[] = [
    { key: "minimal", label: "Minimal", desc: "Only what you asked for." },
    { key: "conservative", label: "Conservative", desc: "Adds risk-management nodes by default." },
    { key: "aggressive", label: "Aggressive", desc: "Suggests optimizations proactively." },
  ];
  return (
    <Step title="Studio AI behavior" sub="Construction only. Trader-mode analysis lives elsewhere.">
      <Group label="Default node-building style">
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          {styles.map((s) => (
            <button key={s.key} onClick={() => setAi({ ...ai, nodeStyle: s.key })}
              className={cn("rounded-lg border p-3 text-left transition-colors",
                ai.nodeStyle === s.key ? "border-violet/50 bg-violet/10" : "border-border bg-elevated hover:border-foreground/30")}>
              <div className="text-sm font-semibold">{s.label}</div>
              <div className="mt-1 text-xs text-muted-foreground">{s.desc}</div>
            </button>
          ))}
        </div>
      </Group>
      <div className="mt-4">
        <RowToggle label="Remember prior builds in session" desc="AI keeps context across strategies you build today."
          on={ai.rememberSession} onChange={(v) => setAi({ ...ai, rememberSession: v })} />
      </div>
    </Step>
  );
}

function StepPayout() {
  const [p, setP] = usePayoutPreference();
  const methods: { id: NonNullable<typeof p.method>; label: string }[] = [
    { id: "ach", label: "ACH" }, { id: "wire", label: "Wire" }, { id: "stripe", label: "Stripe Connect" },
  ];
  return (
    <Step title="Payout preference" sub="Only triggered if a strategy is accepted. Optional.">
      <div className="flex gap-2">
        {methods.map((m) => (
          <Chip key={m.id} on={p.method === m.id} onClick={() => setP({ method: m.id })}>{m.label}</Chip>
        ))}
      </div>
    </Step>
  );
}

function StepWorkspace() {
  const [ws, setWs] = useStudioWorkspaceDefaults();
  return (
    <Step title="Workspace defaults" sub="How your Studio home looks when you open it.">
      <Group label="Default strategy view">
        <div className="flex gap-2">
          {(["grid", "list", "kanban"] as const).map((v) => (
            <Chip key={v} on={ws.view === v} onClick={() => setWs({ ...ws, view: v })}>{v}</Chip>
          ))}
        </div>
      </Group>
      <Group label="Default new-strategy asset class">
        <div className="flex flex-wrap gap-2">
          {ASSETS.map((a) => (
            <Chip key={a.key} on={ws.defaultAssetClass === a.key} onClick={() => setWs({ ...ws, defaultAssetClass: a.key })}>
              {a.label}
            </Chip>
          ))}
        </div>
      </Group>
    </Step>
  );
}

function StepFirstStrategy() {
  const [exp, setExp] = useStudioExperience();
  return (
    <Step title="Your first strategy" sub="We'll open the builder ready for your choice.">
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        {(["template", "ai-describe", "blank"] as BuilderEntry[]).map((k) => (
          <button key={k} onClick={() => setExp({ ...exp, entry: k })}
            className={cn("rounded-lg border p-4 text-left transition-colors",
              exp.entry === k ? "border-violet/50 bg-violet/10" : "border-border bg-elevated hover:border-foreground/30")}>
            <div className="text-sm font-semibold capitalize">{k.replace("-", " ")}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {k === "template" && "Fork a verified template."}
              {k === "ai-describe" && "Describe what you want."}
              {k === "blank" && "Start from an empty canvas."}
            </div>
          </button>
        ))}
      </div>
    </Step>
  );
}

function StepDefaultMode() {
  const [mode, setMode] = useDefaultModeOnLogin();
  return (
    <Step title="Where should we land you?" sub="When you sign in, open this surface by default.">
      <div className="flex gap-2">
        <Chip on={mode === "trader"} onClick={() => setMode("trader")}>Trader</Chip>
        <Chip on={mode === "studio"} onClick={() => setMode("studio")}>Studio</Chip>
      </div>
    </Step>
  );
}

function StepDone({ path }: { path: Path }) {
  return (
    <Step title="You're set" sub="Anything you skipped will show up as a soft prompt on your dashboard.">
      <ul className="space-y-2 text-sm text-muted-foreground">
        <li>· Empty by default — no mock data, no auto-follows.</li>
        <li>· Live market data and news populate from your watched tickers.</li>
        <li>· {path === "developer" ? "Open the Studio builder to start your first strategy." : "Use the Customize button on Home to tweak anything later."}</li>
      </ul>
    </Step>
  );
}

/* ---------------- Primitives ---------------- */

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
        style={{ fontFamily: "var(--font-landing-display)", letterSpacing: "-0.02em" }}>{title}</h1>
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

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick}
      className={cn("rounded-full border px-3.5 py-1.5 text-sm capitalize transition-colors",
        on ? "border-cyan/50 bg-cyan/15 text-cyan" : "border-border bg-elevated text-muted-foreground hover:text-foreground")}>
      {children}
    </button>
  );
}

function RowToggle({ label, desc, on, onChange }: { label: string; desc?: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-border bg-elevated p-3">
      <div>
        <Label className="text-sm">{label}</Label>
        {desc && <p className="text-xs text-muted-foreground">{desc}</p>}
      </div>
      <Switch checked={on} onCheckedChange={onChange} />
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
      className={cn("flex flex-col items-start gap-3 rounded-2xl border p-6 text-left transition-all",
        active ? "scale-[1.01]" : "hover:border-foreground/30")}
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

function toggle<T>(arr: T[], v: T): T[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
}
