import { createFileRoute, Link } from "@tanstack/react-router";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  BookOpen, Rocket, FlaskConical, LineChart, ShieldCheck, Wrench, Plug,
  ArrowRight, CheckCircle2, AlertTriangle, HelpCircle,
} from "lucide-react";

export const Route = createFileRoute("/app/help")({
  head: () => ({ meta: [{ title: "Help & How-to — Bayn" }] }),
  component: HelpPage,
});

function Chip({ kind }: { kind: "live" | "preview" }) {
  return (
    <span className={cn(
      "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide",
      kind === "live"
        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-500"
        : "border-amber-500/40 bg-amber-500/10 text-amber-500",
    )}>
      {kind === "live" ? "Live" : "Preview"}
    </span>
  );
}

function Section({ icon: Icon, title, children }: { icon: typeof BookOpen; title: string; children: React.ReactNode }) {
  return (
    <section className="scroll-mt-20">
      <div className="mb-3 flex items-center gap-2">
        <span className="grid size-8 place-items-center rounded-lg bg-cyan/10 text-cyan"><Icon className="size-4" /></span>
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      </div>
      <Card className="border-border bg-elevated p-5 text-sm leading-relaxed text-muted-foreground">{children}</Card>
    </section>
  );
}

function Steps({ items }: { items: React.ReactNode[] }) {
  return (
    <ol className="space-y-2.5">
      {items.map((it, i) => (
        <li key={i} className="flex gap-3">
          <span className="grid size-5 shrink-0 place-items-center rounded-full bg-cyan/15 font-mono text-[11px] font-semibold text-cyan">{i + 1}</span>
          <span className="min-w-0">{it}</span>
        </li>
      ))}
    </ol>
  );
}

const linkCls = "font-medium text-cyan hover:underline";

function HelpPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8 p-4 md:p-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Help &amp; how-to</h1>
        <p className="text-muted-foreground">Everything you can do in Bayn, step by step — and an honest note on what's live vs still a preview.</p>
      </header>

      {/* TOC */}
      <Card className="border-border bg-elevated/60 p-4">
        <div className="grid grid-cols-1 gap-1.5 text-sm sm:grid-cols-2">
          {[
            ["#big-picture", "The big picture"],
            ["#setup", "Get set up"],
            ["#trader", "Trading (follow strategies)"],
            ["#studio", "Studio (build your own)"],
            ["#paper", "Run a paper trade"],
            ["#live", "Go live (real money)"],
            ["#status", "What's real vs preview"],
            ["#trouble", "Troubleshooting"],
          ].map(([href, label]) => (
            <a key={href} href={href} className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground">
              <ArrowRight className="size-3.5 text-cyan" /> {label}
            </a>
          ))}
        </div>
      </Card>

      <div id="big-picture">
        <Section icon={BookOpen} title="The big picture">
          <p>Bayn is a marketplace <em>and</em> a strategy lab, with two sides to your account:</p>
          <ul className="mt-3 space-y-2">
            <li>• <b className="text-foreground">Trader</b> — follow verified strategies and act on their live <Link to="/app/signals" className={linkCls}>signals</Link> in your own broker.</li>
            <li>• <b className="text-foreground">Studio</b> — build, backtest, validate and run your own strategies. Switch via the account menu → <em>Open my Studio</em>.</li>
          </ul>
          <p className="mt-3"><b className="text-foreground">Bayn never trades for you.</b> Every order is yours to place and confirm — Bayn does the analysis and keeps the record.</p>
        </Section>
      </div>

      <div id="setup">
        <Section icon={Plug} title="Get set up">
          <Steps items={[
            <>Finish <b className="text-foreground">onboarding</b> — choose your path, markets, and account size (this drives suggested position sizes).</>,
            <>Set your <b className="text-foreground">account size &amp; risk</b> anytime in <Link to="/app/settings" className={linkCls}>Settings</Link>.</>,
            <>Check <Link to="/app/settings" className={linkCls}>Settings → Connections</Link> to see which data/AI/broker integrations are configured (green ✓) or missing.</>,
            <>Add your own broker keys (for live trading) under <Link to="/app/settings" className={linkCls}>Settings → API credentials</Link>.</>,
          ]} />
        </Section>
      </div>

      <div id="trader">
        <Section icon={LineChart} title="Trading — follow verified strategies">
          <Steps items={[
            <>Browse the <Link to="/app/catalog" className={linkCls}>Catalog</Link> and <b className="text-foreground">follow</b> a strategy. Look for the <b className="text-foreground">Validated OOS</b> badge — it means the edge survived out-of-sample.</>,
            <>When it fires, a <Link to="/app/signals" className={linkCls}>signal</Link> appears with an entry, stop, target and reasoning — also on your <Link to="/app/home" className={linkCls}>Today</Link> screen.</>,
            <>Open the signal — the <b className="text-foreground">order ticket</b> suggests a size from your account settings.</>,
            <>Place the order in your own broker, then <b className="text-foreground">Log the fill</b> so it's tracked.</>,
            <>Watch results build on <Link to="/app/performance" className={linkCls}>Performance</Link> (real win rate, R-multiples, CSV export).</>,
          ]} />
        </Section>
      </div>

      <div id="studio">
        <Section icon={Wrench} title="Studio — build your own">
          <Steps items={[
            <>Open Studio (account menu → <em>Open my Studio</em>) → <b className="text-foreground">New strategy</b>. Use the <b className="text-foreground">Copilot</b> (describe it in plain English) or the node builder.</>,
            <>Run a <b className="text-foreground">Backtest</b> on real history; review the equity curve and Monte Carlo (risk-of-ruin).</>,
            <>Validate <b className="text-foreground">out-of-sample</b> with a walk-forward analysis.</>,
            <>Promote to a <b className="text-foreground">paper forward test</b> (simulated funds on live data), then optionally deploy live.</>,
          ]} />
          <p className="mt-3">Manage/delete your strategies on the <b className="text-foreground">Strategies</b> and <b className="text-foreground">Backtests</b> pages (grid or list view, with edit/delete).</p>
        </Section>
      </div>

      <div id="paper">
        <Section icon={FlaskConical} title="Run a paper trade">
          <p className="mb-3"><Chip kind="live" /> Paper trading uses <b className="text-foreground">simulated funds on live prices</b> — no real money. Use a <b className="text-foreground">stocks</b> strategy (crypto is real-money only).</p>
          <Steps items={[
            <>Studio → <b className="text-foreground">Copilot</b>: e.g. <em>"20/50 moving-average crossover on SPY"</em> → save.</>,
            <>Studio → <b className="text-foreground">Strategies</b> → ▶ <b className="text-foreground">Backtest now</b> → pick a <b className="text-foreground">recent</b> date range → Run.</>,
            <>On the backtest page → <b className="text-foreground">Continue to OOS test</b> → <b className="text-foreground">Deploy to forward test</b>.</>,
            <>Watch it in <b className="text-foreground">Studio → Live</b>: orders, positions, equity, with Stop / Flatten / Kill-switch.</>,
          ]} />
          <p className="mt-3 text-xs">Fills only happen during US market hours, and only over dates where you have price data.</p>
        </Section>
      </div>

      <div id="live">
        <Section icon={Rocket} title="Go live (real money)">
          <p className="mb-3"><Chip kind="live" /> Deploy Live routes real orders through <b className="text-foreground">your</b> connected broker. Opt-in and confirmed each time.</p>
          <Steps items={[
            <>Connect a real broker key in <Link to="/app/settings" className={linkCls}>Settings → API credentials</Link> (Alpaca live for stocks, Binance.US for crypto).</>,
            <>On the strategy, click <b className="text-foreground">Deploy Live</b> and confirm the real-money dialog.</>,
            <>Monitor in <b className="text-foreground">Studio → Live</b> with per-order and daily-loss caps and the Kill-switch.</>,
          ]} />
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" />
            <span>Bayn never has custody of your funds — money stays in your brokerage. Start small and keep the Kill-switch handy.</span>
          </div>
        </Section>
      </div>

      <div id="status">
        <Section icon={ShieldCheck} title="What's real vs preview">
          <p className="mb-3">Bayn never fakes data. Anything not built yet is labeled, not faked.</p>
          <div className="space-y-2">
            {[
              ["Catalog, signals, backtests, walk-forward, paper sessions, performance", "live"],
              ["Studio AI Copilot (needs Anthropic credit)", "live"],
              ["Deploy Live (needs your broker key)", "live"],
              ["Trader AI Agent — account analysis", "preview"],
              ["Billing / paid plans (no card charged)", "preview"],
              ["One-click broker order routing from a signal", "preview"],
              ["Submit to Bayn catalog (marketplace)", "preview"],
            ].map(([label, kind]) => (
              <div key={label as string} className="flex items-center justify-between gap-3 border-b border-border/60 pb-2 last:border-0">
                <span className="text-foreground/90">{label}</span>
                <Chip kind={kind as "live" | "preview"} />
              </div>
            ))}
          </div>
        </Section>
      </div>

      <div id="trouble">
        <Section icon={HelpCircle} title="Troubleshooting">
          <ul className="space-y-3">
            <li><b className="text-foreground">No stock/crypto data, or a backtest finds nothing:</b> check <Link to="/app/settings" className={linkCls}>Settings → Connections</Link> — the market-data feed must be green. Also backtest a <em>recent</em> date range you actually have bars for.</li>
            <li><b className="text-foreground">AI features say "credit balance too low":</b> the Anthropic account behind the key is out of credits — top up at console.anthropic.com. Trading works without it.</li>
            <li><b className="text-foreground">Copilot times out / errors:</b> a build can take a moment; retry. If it persists, the Anthropic key may be missing credits.</li>
            <li><b className="text-foreground">A backtest is rejected:</b> the error message names the reason (e.g. symbol or timeframe must match the graph). Adjust and re-run.</li>
            <li><b className="text-foreground">A strategy you can't delete:</b> built-in examples aren't yours to remove; your own strategies have a delete (🗑) action.</li>
          </ul>
        </Section>
      </div>

      <div className="flex items-center gap-2 rounded-lg border border-border bg-elevated/60 p-4 text-sm text-muted-foreground">
        <CheckCircle2 className="size-4 text-emerald-500" />
        Still stuck? The on-screen error messages now spell out the real reason — note what it says and where.
      </div>
    </div>
  );
}
