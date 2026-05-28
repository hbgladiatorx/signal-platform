import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Check, ArrowRight, Sparkles, ShieldCheck } from "lucide-react";

export const Route = createFileRoute("/pricing")({
  head: () => ({
    meta: [
      { title: "Pricing — Bayn" },
      {
        name: "description",
        content:
          "Simple, honest pricing. Browse the catalog free. Upgrade for live signals, the Studio, and advanced backtesting.",
      },
      { property: "og:title", content: "Pricing — Bayn" },
      {
        property: "og:description",
        content:
          "Free to browse verified strategies. Upgrade for live signals, the Studio and advanced backtesting.",
      },
    ],
  }),
  component: PricingPage,
});

type Plan = {
  id: string;
  name: string;
  tag?: string;
  blurb: string;
  monthly: number;
  yearly: number;
  highlight?: boolean;
  cta: string;
  features: string[];
};

const PLANS: Plan[] = [
  {
    id: "free",
    name: "Explorer",
    blurb: "Browse the verified catalog. No card required.",
    monthly: 0,
    yearly: 0,
    cta: "Start free",
    features: [
      "Full strategy catalog",
      "Historical performance + filter pipeline detail",
      "Weekly market digest",
      "Community forum",
    ],
  },
  {
    id: "pro",
    name: "Pro Trader",
    tag: "Most popular",
    blurb: "Live signals + mobile alerts for serious followers.",
    monthly: 29,
    yearly: 24,
    highlight: true,
    cta: "Start 14-day trial",
    features: [
      "Everything in Explorer",
      "Real-time signal feed (push + email)",
      "Follow up to 25 strategies",
      "Performance tracker vs. live results",
      "Chart context per signal",
      "Priority support",
    ],
  },
  {
    id: "quant",
    name: "Quant",
    blurb: "Build your own strategies in the Studio and trade them live.",
    monthly: 89,
    yearly: 74,
    cta: "Open the Studio",
    features: [
      "Everything in Pro Trader",
      "Node-based Strategy Studio",
      "AI co-builder (prompt → graph)",
      "Backtest + Monte Carlo + walk-forward",
      "Unlimited custom strategies",
      "Deploy strategies to live signal feed",
    ],
  },
];

function PricingPage() {
  const [yearly, setYearly] = useState(true);

  return (
    <div
      className="min-h-screen bg-background text-foreground"
      style={{ fontFamily: "var(--font-landing-body)" }}
    >
      {/* Header */}
      <header className="sticky top-0 z-30 bg-transparent">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 md:px-10">
          <Link to="/" className="flex items-center gap-2.5 text-base font-semibold">
            <div
              className="grid size-8 place-items-center rounded-lg font-bold text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}
            >
              B
            </div>
            <span style={{ fontFamily: "var(--font-landing-display)", letterSpacing: "-0.02em" }}>Bayn</span>
          </Link>
          <div className="flex items-center gap-2">
            <Button variant="ghost" asChild>
              <Link to="/auth">Sign in</Link>
            </Button>
            <Button
              asChild
              className="text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}
            >
              <Link to="/app/catalog">
                Start free <ArrowRight className="ml-1.5 size-4" />
              </Link>
            </Button>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section
        className="relative overflow-hidden"
        style={{
          background:
            "radial-gradient(ellipse 80% 50% at 50% 0%, color-mix(in oklab, var(--emerald) 18%, transparent), transparent 70%)",
        }}
      >
        <div className="mx-auto max-w-3xl px-6 pb-12 pt-20 text-center md:px-10 md:pt-24">
          <div
            className="mx-auto mb-6 inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs"
            style={{
              borderColor: "color-mix(in oklab, var(--brand-gold) 40%, transparent)",
              background: "color-mix(in oklab, var(--brand-gold) 10%, transparent)",
              color: "var(--brand-gold)",
            }}
          >
            <Sparkles className="size-3.5" />
            <span className="font-medium uppercase tracking-wider">Simple, honest pricing</span>
          </div>
          <h1
            className="text-balance text-4xl font-bold leading-[1.05] md:text-6xl"
            style={{ fontFamily: "var(--font-landing-display)", letterSpacing: "-0.025em" }}
          >
            Pay for the edge. <span className="landing-grad">Not the noise.</span>
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-balance text-base text-muted-foreground md:text-lg">
            Browse the catalog free, forever. Upgrade when you want live signals, mobile alerts or your own
            strategies in the Studio.
          </p>

          {/* Billing toggle */}
          <div className="mt-9 inline-flex items-center gap-3 rounded-full border border-border bg-elevated p-1 text-sm">
            <button
              onClick={() => setYearly(false)}
              className={`rounded-full px-4 py-1.5 transition-colors ${
                !yearly ? "bg-background text-foreground" : "text-muted-foreground"
              }`}
            >
              Monthly
            </button>
            <button
              onClick={() => setYearly(true)}
              className={`flex items-center gap-2 rounded-full px-4 py-1.5 transition-colors ${
                yearly ? "bg-background text-foreground" : "text-muted-foreground"
              }`}
            >
              Yearly
              <span
                className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                style={{
                  background: "color-mix(in oklab, var(--emerald) 22%, transparent)",
                  color: "var(--emerald-glow)",
                }}
              >
                −2 mo
              </span>
            </button>
          </div>
        </div>

        <style>{`
          .landing-grad {
            background: var(--gradient-gold-emerald);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
          }
        `}</style>
      </section>

      {/* Plans */}
      <section className="mx-auto max-w-6xl px-6 pb-20 pt-6 md:px-10 md:pb-28">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          {PLANS.map((plan) => (
            <PlanCard key={plan.id} plan={plan} yearly={yearly} />
          ))}
        </div>

        <p className="mt-8 flex items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
          <ShieldCheck className="size-3.5 text-emerald-glow" />
          Cancel anytime. Bayn never trades on your behalf — every order requires your confirmation.
        </p>
      </section>

      {/* Comparison */}
      <section className="border-t border-border bg-elevated/40">
        <div className="mx-auto max-w-5xl px-6 py-16 md:px-10 md:py-20">
          <h2
            className="mb-8 text-center text-2xl font-bold md:text-3xl"
            style={{ fontFamily: "var(--font-landing-display)" }}
          >
            What's included
          </h2>
          <div className="overflow-hidden rounded-2xl border border-border bg-background">
            <table className="w-full text-sm">
              <thead className="bg-elevated">
                <tr className="text-left">
                  <th className="px-5 py-4 font-medium text-muted-foreground">Feature</th>
                  <th className="px-5 py-4 text-center font-medium">Explorer</th>
                  <th className="px-5 py-4 text-center font-medium" style={{ color: "var(--emerald-glow)" }}>
                    Pro Trader
                  </th>
                  <th className="px-5 py-4 text-center font-medium" style={{ color: "var(--brand-gold)" }}>
                    Quant
                  </th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["Full verified catalog", true, true, true],
                  ["Live signal feed", false, true, true],
                  ["Mobile + email alerts", false, true, true],
                  ["Follow multiple strategies", "Up to 3", "Up to 25", "Unlimited"],
                  ["Strategy Studio (build your own)", false, false, true],
                  ["AI co-builder", false, false, true],
                  ["Backtest + Monte Carlo + walk-forward", false, false, true],
                  ["Priority support", false, true, true],
                ].map(([label, e, p, q], i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="px-5 py-3.5">{label as string}</td>
                    <Cell value={e} />
                    <Cell value={p} />
                    <Cell value={q} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="mx-auto max-w-3xl px-6 py-20 md:px-10 md:py-24">
        <h2
          className="mb-8 text-center text-2xl font-bold md:text-3xl"
          style={{ fontFamily: "var(--font-landing-display)" }}
        >
          Pricing FAQ
        </h2>
        <div className="space-y-3">
          {[
            {
              q: "Can I really use Bayn without paying?",
              a: "Yes. The Explorer plan is free forever and gives you full access to browse every verified strategy, its track record and the filter it passed.",
            },
            {
              q: "Do you take a cut of my trading profits?",
              a: "No. Bayn never connects to your broker and never takes a percentage of trades. You pay a flat subscription, you keep 100% of your trading upside.",
            },
            {
              q: "Can I cancel anytime?",
              a: "Yes. Cancel from your account at any time. You keep paid features until the end of your current billing period.",
            },
            {
              q: "Is there a refund policy?",
              a: "Pro Trader includes a 14-day free trial. After that we refund within 7 days if you haven't used the live signal feed.",
            },
          ].map(({ q, a }) => (
            <details
              key={q}
              className="group rounded-xl border border-border bg-elevated p-5 transition-colors hover:border-foreground/30"
            >
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
          <Link to="/" className="hover:text-foreground">
            Back to home
          </Link>
        </div>
      </footer>
    </div>
  );
}

function PlanCard({ plan, yearly }: { plan: Plan; yearly: boolean }) {
  const price = yearly ? plan.yearly : plan.monthly;
  const highlight = plan.highlight;

  return (
    <div
      className="relative flex flex-col rounded-2xl border p-7"
      style={{
        background: highlight
          ? "linear-gradient(180deg, color-mix(in oklab, var(--emerald) 12%, var(--elevated)), var(--elevated))"
          : "var(--elevated)",
        borderColor: highlight ? "color-mix(in oklab, var(--emerald) 55%, var(--border))" : "var(--border)",
        boxShadow: highlight ? "var(--shadow-emerald)" : undefined,
      }}
    >
      {plan.tag && (
        <div
          className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-brand-cream"
          style={{ background: "var(--gradient-emerald)" }}
        >
          {plan.tag}
        </div>
      )}

      <div className="mb-1 text-sm font-medium text-muted-foreground">{plan.name}</div>
      <div className="flex items-end gap-1">
        <span
          className="text-5xl font-bold"
          style={{ fontFamily: "var(--font-landing-display)", letterSpacing: "-0.025em" }}
        >
          ${price}
        </span>
        <span className="mb-2 text-sm text-muted-foreground">/mo</span>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{plan.blurb}</p>

      <Button
        asChild
        className="mt-6 h-11 w-full"
        style={
          highlight
            ? { background: "var(--gradient-emerald)", color: "var(--brand-cream)", boxShadow: "var(--shadow-emerald)" }
            : { background: "transparent", border: "1px solid var(--border)", color: "var(--foreground)" }
        }
      >
        <Link to={plan.id === "quant" ? "/studio/home" : "/auth"}>{plan.cta}</Link>
      </Button>

      <ul className="mt-7 space-y-2.5 text-sm">
        {plan.features.map((f) => (
          <li key={f} className="flex items-start gap-2.5 text-muted-foreground">
            <Check
              className="mt-0.5 size-4 shrink-0"
              style={{ color: highlight ? "var(--emerald-glow)" : "var(--brand-gold)" }}
            />
            <span className="text-foreground/90">{f}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Cell({ value }: { value: boolean | string }) {
  if (typeof value === "string") {
    return <td className="px-5 py-3.5 text-center text-sm text-muted-foreground">{value}</td>;
  }
  return (
    <td className="px-5 py-3.5 text-center">
      {value ? (
        <Check className="mx-auto size-4 text-emerald-glow" />
      ) : (
        <span className="text-muted-foreground/40">—</span>
      )}
    </td>
  );
}
