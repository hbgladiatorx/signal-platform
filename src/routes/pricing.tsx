import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ArrowRight, ShieldCheck, Sparkles, Layers, BadgeCheck } from "lucide-react";
import { BillingToggle } from "@/components/billing/BillingToggle";
import { PricingTable } from "@/components/billing/PricingTable";
import type { Audience, Billing, TierId } from "@/lib/api/billing";

export const Route = createFileRoute("/pricing")({
  head: () => ({
    meta: [
      { title: "Pricing — Bayn" },
      { name: "description", content: "Institutional-grade signals and a desk-grade quant lab. Pricing for serious operators." },
      { property: "og:title", content: "Pricing — Bayn" },
      { property: "og:description", content: "Verified signals for traders. Desk-grade tooling for builders." },
    ],
  }),
  component: PricingPage,
});

function PricingPage() {
  const nav = useNavigate();
  const [audience, setAudience] = useState<Audience>("trader");
  const [billing, setBilling] = useState<Billing>("annual");
  const accentVar = audience === "developer" ? "var(--violet)" : "var(--cyan)";

  const go = (_id?: TierId) => nav({ to: "/onboarding" });

  return (
    <div className="min-h-screen bg-background text-foreground" style={{ fontFamily: "var(--font-landing-body)" }}>
      <header className="sticky top-0 z-30 border-b border-border/40 bg-background/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 md:px-10">
          <Link to="/" className="flex items-center gap-2.5 text-base font-semibold">
            <div className="grid size-8 place-items-center rounded-lg font-bold text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}>B</div>
            <span style={{ fontFamily: "var(--font-landing-display)", letterSpacing: "-0.02em" }}>Bayn</span>
          </Link>
          <div className="flex items-center gap-2">
            <Button variant="ghost" asChild><Link to="/auth">Sign in</Link></Button>
            <Button asChild className="text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}>
              <Link to="/auth">Get started <ArrowRight className="ml-1.5 size-4" /></Link>
            </Button>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden"
        style={{ background: `radial-gradient(ellipse 80% 50% at 50% 0%, color-mix(in oklab, ${accentVar} 16%, transparent), transparent 70%)` }}>
        <div className="mx-auto max-w-3xl px-6 pb-12 pt-20 text-center md:px-10 md:pt-24">
          <div className="mx-auto mb-6 inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs"
            style={{
              borderColor: "color-mix(in oklab, var(--brand-gold) 40%, transparent)",
              background: "color-mix(in oklab, var(--brand-gold) 10%, transparent)",
              color: "var(--brand-gold)",
            }}>
            <Sparkles className="size-3.5" />
            <span className="font-medium uppercase tracking-wider">Verified pipeline · institutional access</span>
          </div>
          <h1 className="text-balance text-4xl font-bold leading-[1.05] md:text-6xl"
            style={{ fontFamily: "var(--font-landing-display)", letterSpacing: "-0.025em" }}>
            Priced for operators who <span style={{ color: accentVar }}>take this seriously.</span>
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-balance text-base text-muted-foreground md:text-lg">
            The validation pipeline is the product. Every strategy in the catalog survived the same gauntlet our desks use.
          </p>

          {/* Audience tabs */}
          <div className="mx-auto mt-9 inline-flex rounded-full border border-border bg-elevated p-1">
            {(["trader", "developer"] as Audience[]).map((a) => {
              const active = audience === a;
              const c = a === "developer" ? "var(--violet)" : "var(--cyan)";
              return (
                <button key={a} onClick={() => setAudience(a)}
                  className="flex items-center gap-2 rounded-full px-5 py-2 text-sm font-medium transition-colors"
                  style={active ? { background: c, color: "var(--background)" } : { color: "var(--muted-foreground)" }}>
                  {a === "trader" ? <BadgeCheck className="size-4" /> : <Layers className="size-4" />}
                  {a === "trader" ? "For Traders" : "For Developers"}
                </button>
              );
            })}
          </div>

          <div className="mt-6 flex justify-center">
            <BillingToggle value={billing} onChange={setBilling} accent={audience === "developer" ? "violet" : "cyan"} />
          </div>
        </div>
      </section>

      {/* Free strategies callout — trader only */}
      {audience === "trader" && (
        <section className="mx-auto max-w-6xl px-6 md:px-10">
          <div className="rounded-2xl border p-5 md:p-7"
            style={{
              borderColor: "color-mix(in oklab, var(--brand-gold) 35%, var(--border))",
              background: "linear-gradient(135deg, color-mix(in oklab, var(--brand-gold) 8%, var(--elevated)), var(--elevated))",
            }}>
            <div className="flex flex-col items-start gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="mb-1.5 inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider"
                  style={{ color: "var(--brand-gold)" }}>
                  <BadgeCheck className="size-3.5" /> Free · Verified
                </div>
                <h3 className="text-lg font-semibold md:text-xl" style={{ fontFamily: "var(--font-landing-display)" }}>
                  Four entry-grade verified strategies. Free, forever. Real signals.
                </h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  One per asset class — Stocks, Crypto, Options, Futures. Live tracked. No card required. Proof the pipeline is real.
                </p>
              </div>
              <Button asChild className="text-brand-cream"
                style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}>
                <Link to="/auth">Activate free strategies <ArrowRight className="ml-1.5 size-4" /></Link>
              </Button>
            </div>
          </div>
        </section>
      )}

      {/* Developer positioning */}
      {audience === "developer" && (
        <section className="mx-auto max-w-3xl px-6 text-center md:px-10">
          <h2 className="text-xl font-semibold md:text-2xl" style={{ fontFamily: "var(--font-landing-display)" }}>
            The tools institutional quants pay millions to access. For one operator.
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Node-based backtesting, multi-asset data, the agentic build loop. Studio is priced above the trader tiers by design — a trader buys outcomes, a developer buys the means of production.
          </p>
        </section>
      )}

      {/* Tables */}
      <section className="mx-auto max-w-6xl px-6 py-12 md:px-10 md:py-16">
        <PricingTable audience={audience} billing={billing} onSelect={go} />

        <p className="mt-8 flex items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
          <ShieldCheck className="size-3.5" style={{ color: "var(--emerald-glow)" }} />
          Bayn never trades on your behalf. Every order requires your confirmation.
        </p>
      </section>

      {/* Revenue share */}
      {audience === "developer" && (
        <section className="mx-auto max-w-5xl px-6 pb-16 md:px-10">
          <div className="rounded-2xl border border-border bg-elevated p-7"
            style={{ background: "linear-gradient(135deg, color-mix(in oklab, var(--violet) 8%, var(--elevated)), var(--elevated))" }}>
            <div className="mb-2 text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--violet)" }}>
              Revenue share
            </div>
            <h3 className="text-lg font-semibold md:text-xl" style={{ fontFamily: "var(--font-landing-display)" }}>
              The subscription pays for the lab. The catalog is the upside.
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Strategies you build, validate and submit can be accepted into Bayn's catalog. Every trader subscription
              to that strategy pays you a recurring revenue share — Quant tier earns the standard rate, Principal earns the top rate.
            </p>
          </div>
        </section>
      )}

      {/* FAQ */}
      <section className="mx-auto max-w-3xl px-6 py-16 md:px-10 md:py-20">
        <h2 className="mb-8 text-center text-2xl font-bold md:text-3xl"
          style={{ fontFamily: "var(--font-landing-display)" }}>Pricing FAQ</h2>
        <div className="space-y-3">
          {[
            { q: "What does 'verified' mean?",
              a: "Every catalog strategy survived the same validation gauntlet our desks use: multi-regime backtest, walk-forward, Monte Carlo, and a tracked live forward-test period. Performance is measured against live results — not just historical curves." },
            { q: "Can I switch tiers anytime?",
              a: "Yes. Upgrade instantly. Downgrades take effect at the end of the current billing period. Annual plans are credited pro-rata on upgrade." },
            { q: "What's the difference between Trader and Developer?",
              a: "Trader is about following verified strategies. Developer (Studio) is about building, backtesting and deploying your own. Many operators run both — your account can hold one of each." },
            { q: "How does revenue share work?",
              a: "Studio Quant and Principal users can submit strategies for catalog review. Accepted strategies earn a recurring share on every trader subscription to that strategy. Principal earns the highest rate." },
            { q: "Do I need a brokerage?",
              a: "No to receive signals. Yes to execute. Bayn never connects to your broker — you either fire orders manually or run the agentic loop through your own connected account." },
          ].map(({ q, a }) => (
            <details key={q} className="group rounded-xl border border-border bg-elevated p-5 transition-colors hover:border-foreground/30">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                <span>{q}</span>
                <ArrowRight className="size-4 shrink-0 transition-transform group-open:rotate-90" />
              </summary>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{a}</p>
            </details>
          ))}
        </div>
      </section>

      <footer className="border-t border-border px-6 py-8 md:px-10">
        <div className="mx-auto flex max-w-7xl items-center justify-between text-xs text-muted-foreground">
          <span>© {new Date().getFullYear()} Bayn</span>
          <Link to="/" className="hover:text-foreground">Back to home</Link>
        </div>
      </footer>
    </div>
  );
}
