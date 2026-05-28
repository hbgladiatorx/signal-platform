import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import {
  BadgeCheck,
  ShieldCheck,
  Activity,
  ArrowRight,
  LineChart,
  Wrench,
  TrendingUp,
  Sparkles,
  Filter,
  Lock,
  Zap,
  Users,
} from "lucide-react";
import { Disclaimer } from "@/components/common/Disclaimer";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Bayn — Verified trading signals that survived the filter" },
      {
        name: "description",
        content:
          "Bayn publishes only trading strategies that survive a 5-stage edge pipeline. Backtest, out-of-sample, forward-test, live review, continuous monitoring. You stay in control.",
      },
      { property: "og:title", content: "Bayn — Signals that survived the filter" },
      {
        property: "og:description",
        content:
          "A curated catalog of trading strategies measured honestly. Stocks, crypto, options, futures. You confirm every trade.",
      },
    ],
  }),
  component: Landing,
});
function Landing() {
  useEffect(() => {
    const els = document.querySelectorAll<HTMLElement>("[data-reveal]");
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-revealed");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -60px 0px" }
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  return (

    <div
      className="min-h-screen bg-background text-foreground"
      style={{
        fontFamily: "var(--font-landing-body)",
      }}
    >
      <style>{`
        .landing-display { font-family: var(--font-landing-display); letter-spacing: -0.025em; }
        .landing-grad-text {
          background: var(--gradient-gold-emerald);
          -webkit-background-clip: text;
          background-clip: text;
          color: transparent;
        }
        .landing-bento-card {
          position: relative;
          border-radius: 1.25rem;
          border: 1px solid var(--border);
          background: var(--elevated);
          overflow: hidden;
          transition: border-color 200ms, transform 200ms;
        }
        .landing-bento-card:hover { border-color: color-mix(in oklab, var(--emerald) 50%, transparent); }
        .landing-glow-emerald::before {
          content: "";
          position: absolute;
          inset: -40%;
          background: radial-gradient(circle at 30% 20%, color-mix(in oklab, var(--emerald-glow) 25%, transparent), transparent 60%);
          pointer-events: none;
        }
        .landing-glow-gold::before {
          content: "";
          position: absolute;
          inset: -40%;
          background: radial-gradient(circle at 70% 20%, color-mix(in oklab, var(--brand-gold) 22%, transparent), transparent 60%);
          pointer-events: none;
        }
        .landing-hero-grad {
          background:
            radial-gradient(ellipse 80% 60% at 50% 0%, color-mix(in oklab, var(--emerald) 25%, transparent), transparent 70%),
            radial-gradient(ellipse 60% 50% at 80% 30%, color-mix(in oklab, var(--brand-gold) 12%, transparent), transparent 70%);
        }
        .ticker-track { animation: ticker 35s linear infinite; }
        @keyframes ticker { from { transform: translateX(0); } to { transform: translateX(-50%); } }
        .equity-rise {
          stroke-dasharray: 600;
          stroke-dashoffset: 600;
          animation: draw 2.4s ease-out forwards;
        }
        @keyframes draw { to { stroke-dashoffset: 0; } }

        /* Scroll reveal */
        [data-reveal] {
          opacity: 0;
          transform: translateY(28px);
          transition: opacity 700ms cubic-bezier(0.22, 1, 0.36, 1),
                      transform 700ms cubic-bezier(0.22, 1, 0.36, 1);
          transition-delay: var(--reveal-delay, 0ms);
          will-change: opacity, transform;
        }
        [data-reveal].is-revealed {
          opacity: 1;
          transform: translateY(0);
        }
        @media (prefers-reduced-motion: reduce) {
          [data-reveal] { opacity: 1; transform: none; transition: none; }
          .ticker-track, .equity-rise, .hero-shimmer, .hero-rise { animation: none !important; }
        }

        /* Hero text animations */
        .hero-rise {
          opacity: 0;
          transform: translateY(20px);
          animation: heroRise 900ms cubic-bezier(0.22, 1, 0.36, 1) forwards;
          animation-delay: var(--rise-delay, 0ms);
        }
        @keyframes heroRise {
          to { opacity: 1; transform: translateY(0); }
        }
        .hero-shimmer {
          background-size: 200% auto;
          animation: shimmer 6s linear infinite;
        }
        @keyframes shimmer {
          0% { background-position: 0% center; }
          100% { background-position: 200% center; }
        }
      `}</style>


      {/* HEADER */}
      <header className="sticky top-0 z-30 bg-background/60 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-4 md:px-10">
          <Link to="/" className="flex items-center gap-2.5 text-base font-semibold">
            <div
              className="grid size-8 place-items-center rounded-lg font-bold text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}
            >
              B
            </div>
            <span className="landing-display tracking-tight">Bayn</span>
          </Link>

          <nav className="landing-display hidden md:flex absolute left-1/2 -translate-x-1/2 items-center gap-1 rounded-full border border-border/70 bg-transparent px-3 py-2 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
            <a href="#pipeline" className="rounded-full px-4 py-1.5 transition-colors hover:text-foreground">The Filter</a>
            <a href="#catalog" className="rounded-full px-4 py-1.5 transition-colors hover:text-foreground">Catalog</a>
            <a href="#studio" className="rounded-full px-4 py-1.5 transition-colors hover:text-foreground">Studio</a>
            <a href="#proof" className="rounded-full px-4 py-1.5 transition-colors hover:text-foreground">Proof</a>
          </nav>


          <div className="flex items-center gap-2">
            <Button variant="ghost" asChild className="hidden sm:inline-flex">
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


      {/* HERO */}
      <section className="relative overflow-hidden landing-hero-grad">
        <div className="mx-auto max-w-7xl px-6 pb-16 pt-20 md:px-10 md:pt-28">
          <div className="mx-auto max-w-4xl text-center">
            <div
              className="hero-rise mx-auto mb-7 inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs"
              style={{
                borderColor: "color-mix(in oklab, var(--brand-gold) 40%, transparent)",
                background: "color-mix(in oklab, var(--brand-gold) 10%, transparent)",
                color: "var(--brand-gold)",
                ["--rise-delay" as any]: "0ms",
              }}
            >
              <BadgeCheck className="size-3.5" />
              <span className="font-medium">A two-sided market for verified trading edge</span>
            </div>
            <h1
              className="hero-rise landing-display text-balance text-5xl font-bold leading-[1.05] md:text-7xl lg:text-[5.5rem]"
              style={{ ["--rise-delay" as any]: "120ms" }}
            >
              <span className="landing-grad-text hero-shimmer">Trade</span> the signal.{" "}
              <span className="landing-grad-text hero-shimmer">Build</span> the signal.
            </h1>
            <p
              className="hero-rise mx-auto mt-7 max-w-2xl text-balance text-lg text-muted-foreground md:text-xl"
              style={{ ["--rise-delay" as any]: "260ms" }}
            >
              Bayn is the marketplace where quants ship verified strategies and traders follow them.
              <span className="text-foreground"> One filter. Both sides win.</span>
            </p>
            <div
              className="hero-rise mt-9 grid gap-3 sm:grid-cols-2 sm:gap-4"
              style={{ ["--rise-delay" as any]: "380ms" }}
            >
              <Button
                size="lg"
                asChild
                className="h-12 px-6 text-base text-brand-cream"
                style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}
              >
                <Link to="/app/catalog">
                  <LineChart className="mr-1.5 size-4" /> I'm a trader
                </Link>
              </Button>
              <Button
                size="lg"
                asChild
                className="h-12 px-6 text-base"
                style={{
                  background: "color-mix(in oklab, var(--brand-gold) 18%, transparent)",
                  border: "1px solid color-mix(in oklab, var(--brand-gold) 50%, transparent)",
                  color: "var(--brand-gold)",
                  boxShadow: "var(--shadow-gold)",
                }}
              >
                <Link to="/studio/home">
                  <Wrench className="mr-1.5 size-4" /> I'm a developer
                </Link>
              </Button>
            </div>
            <div
              className="hero-rise mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-muted-foreground"
              style={{ ["--rise-delay" as any]: "500ms" }}
            >
              <span className="flex items-center gap-1.5"><Lock className="size-3.5" /> No auto-trading</span>
              <span className="opacity-50">·</span>
              <span className="flex items-center gap-1.5"><Zap className="size-3.5" /> Free to start</span>
              <span className="opacity-50">·</span>
              <span className="flex items-center gap-1.5"><Users className="size-3.5" /> 4,200+ traders · 380+ devs</span>
            </div>
          </div>



          {/* Live ticker */}
          <div className="mt-14 overflow-hidden rounded-xl border border-border/60 bg-elevated/60">
            <div className="flex ticker-track" style={{ width: "max-content" }}>
              {[...Array(2)].map((_, dup) => (
                <div key={dup} className="flex shrink-0 items-center gap-8 px-6 py-3 font-mono text-xs">
                  {[
                    { sym: "BTC-PERP", side: "LONG", r: "+2.1R", strat: "Trend-Following v3" },
                    { sym: "SPY", side: "SHORT", r: "+1.4R", strat: "Mean Reversion Pro" },
                    { sym: "NVDA", side: "LONG", r: "+0.9R", strat: "Earnings Drift" },
                    { sym: "ES", side: "LONG", r: "+1.8R", strat: "Opening Range" },
                    { sym: "ETH", side: "SHORT", r: "+1.2R", strat: "Funding Skew" },
                    { sym: "AAPL", side: "LONG", r: "+0.6R", strat: "Gap-Fill" },
                    { sym: "QQQ", side: "LONG", r: "+2.4R", strat: "Momentum Burst" },
                  ].map((s, i) => (
                    <div key={`${dup}-${i}`} className="flex items-center gap-2">
                      <span className="rounded bg-success/15 px-1.5 py-0.5 text-[10px] uppercase text-success">Live</span>
                      <span className="text-foreground">{s.sym}</span>
                      <span className={s.side === "LONG" ? "text-success" : "text-danger"}>{s.side}</span>
                      <span className="text-brand-gold">{s.r}</span>
                      <span className="text-muted-foreground">· {s.strat}</span>
                      <span className="text-muted-foreground/40">|</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* SHARED FILTER (neutral — the bridge between both sides) */}
      <section id="pipeline" className="mx-auto max-w-7xl px-6 pb-16 pt-10 md:px-10 md:pb-24">
        <div className="mb-8 text-center">
          <div className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-brand-gold">The bridge</div>
          <h2 className="landing-display mx-auto max-w-3xl text-balance text-3xl font-bold tracking-tight md:text-5xl">
            One filter sits between <span className="landing-grad-text">builders and traders</span>.
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-sm text-muted-foreground md:text-base">
            Devs submit. The filter measures. Traders only ever see what survived.
          </p>
        </div>

        <div className="landing-bento-card landing-glow-emerald">
          <div className="relative z-10 p-7 md:p-9">
            <div className="mb-5 flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-emerald-glow">
              <Filter className="size-3.5" /> The 5-stage filter
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
              {[
                { n: "01", t: "Backtest", v: "8,420" },
                { n: "02", t: "Out-of-Sample", v: "2,180" },
                { n: "03", t: "Forward-Test", v: "640" },
                { n: "04", t: "Live Review", v: "210" },
                { n: "05", t: "Published", v: "127" },
              ].map((s, i) => (
                <div
                  key={s.n}
                  className="rounded-lg border border-border/60 p-4"
                  style={{ background: `color-mix(in oklab, var(--emerald) ${4 + i * 4}%, transparent)` }}
                >
                  <div className="font-mono text-[10px] text-muted-foreground">{s.n}</div>
                  <div className="mt-1 text-sm font-medium">{s.t}</div>
                  <div className="mt-2 font-mono text-base text-brand-gold">{s.v}</div>
                </div>
              ))}
            </div>
            <p className="mt-5 text-sm text-muted-foreground">
              98.5% of submitted strategies are rejected. Survivors are continuously monitored — pulled the moment edge decays.
            </p>
          </div>
        </div>
      </section>

      {/* TWO-SIDED SYMMETRIC BENTO */}
      <section id="catalog" className="mx-auto max-w-7xl px-6 pb-20 md:px-10 md:pb-28">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* === TRADER SIDE === */}
          <SideColumn
            tone="emerald"
            tag="For traders"
            tagIcon={LineChart}
            title="Follow verified signals"
            subtitle="Browse the catalog. Subscribe to strategies that fit your style. Confirm every trade through your own broker."
            ctaText="Enter the trader app"
            ctaTo="/app/catalog"
            cards={[
              {
                kind: "metric",
                title: "Live performance",
                icon: TrendingUp,
                bigValue: "+37.4%",
                bigLabel: "Avg published-strategy return · 12mo",
                stats: [
                  { label: "Sharpe", value: "1.84" },
                  { label: "Win rate", value: "58%" },
                  { label: "Max DD", value: "−9%" },
                ],
              },
              {
                kind: "signal",
                title: "Just fired",
                icon: Activity,
              },
              {
                kind: "feature",
                title: "You stay in control",
                icon: Lock,
                body: "Bayn never executes for you. Zero broker keys to browse. Every order is yours to confirm.",
              },
              {
                kind: "bullets",
                title: "What you get",
                icon: BadgeCheck,
                bullets: [
                  "Free catalog · no card required",
                  "Mobile signal feed with chart context",
                  "Track real PnL vs. published backtest",
                ],
              },
            ]}
          />

          {/* === DEVELOPER SIDE === */}
          <SideColumn
            tone="gold"
            tag="For developers"
            tagIcon={Wrench}
            title="Build & monetize strategies"
            subtitle="Compose in a node builder or describe in plain English. Backtest, run OOS, forward-test, submit. Earn revenue share when published."
            ctaText="Open the Studio"
            ctaTo="/studio/home"
            cards={[
              {
                kind: "metric",
                title: "Builder economics",
                icon: TrendingUp,
                bigValue: "30%",
                bigLabel: "Revenue share on every subscriber",
                stats: [
                  { label: "Top dev / mo", value: "$8.4k" },
                  { label: "Avg subs", value: "94" },
                  { label: "Payout", value: "Monthly" },
                ],
              },
              {
                kind: "equity",
                title: "Backtest engine",
                icon: Activity,
              },
              {
                kind: "feature",
                title: "AI co-builder",
                icon: Sparkles,
                body: "Describe a strategy in prose and the builder wires the graph. Tweak nodes, swap timeframes, ship.",
              },
              {
                kind: "bullets",
                title: "What you get",
                icon: BadgeCheck,
                bullets: [
                  "Node-based builder + AI prompt mode",
                  "Monte Carlo + walk-forward built in",
                  "Distribution to 4,200+ traders on day one",
                ],
              },
            ]}
          />
        </div>
      </section>


      {/* PROOF / TRUST */}
      <section id="proof" className="border-y border-border/60 bg-elevated/40">
        <div className="mx-auto grid max-w-7xl grid-cols-2 gap-6 px-6 py-12 md:grid-cols-4 md:px-10">
          {[
            { v: "127", l: "Live strategies" },
            { v: "4,200+", l: "Active traders" },
            { v: "98.5%", l: "Submission rejection rate" },
            { v: "24/7", l: "Edge-decay monitoring" },
          ].map((s) => (
            <div key={s.l}>
              <div className="landing-display text-3xl font-bold text-brand-cream md:text-4xl">{s.v}</div>
              <div className="mt-1 text-xs text-muted-foreground md:text-sm">{s.l}</div>
            </div>
          ))}
        </div>
      </section>

      {/* THREE PILLARS */}
      <section className="mx-auto max-w-7xl px-6 py-20 md:px-10 md:py-28">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          {[
            {
              icon: ShieldCheck,
              title: "Verified, not promoted",
              body: "We don't take a strategy's word for it. Every published strategy clears out-of-sample and live forward-tests before reaching the catalog.",
            },
            {
              icon: Activity,
              title: "Live, not historical",
              body: "Signals derive from rules running on live market data — stocks, crypto, options, futures. You see them the moment they fire.",
            },
            {
              icon: BadgeCheck,
              title: "You're still the trader",
              body: "Bayn never trades your account. Every order requires your confirmation. We measure outcomes honestly so you decide what to follow.",
            },
          ].map(({ icon: Icon, title, body }) => (
            <div key={title} className="rounded-2xl border border-border bg-elevated p-7">
              <div
                className="mb-5 grid size-10 place-items-center rounded-lg"
                style={{
                  background: "color-mix(in oklab, var(--emerald) 15%, transparent)",
                  color: "var(--emerald-glow)",
                }}
              >
                <Icon className="size-5" />
              </div>
              <h3 className="landing-display text-lg font-semibold">{title}</h3>
              <p className="mt-2 text-sm text-muted-foreground">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* FINAL CTA */}
      <section className="mx-auto max-w-7xl px-6 pb-24 md:px-10">
        <div
          className="relative overflow-hidden rounded-3xl border p-10 text-center md:p-16"
          style={{
            background: "var(--gradient-emerald)",
            borderColor: "color-mix(in oklab, var(--brand-gold) 30%, transparent)",
            boxShadow: "var(--shadow-emerald)",
          }}
        >
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(circle at 30% 20%, color-mix(in oklab, var(--brand-gold) 25%, transparent), transparent 60%)",
            }}
          />
          <div className="relative">
            <h2 className="landing-display mx-auto max-w-3xl text-balance text-4xl font-bold text-brand-cream md:text-6xl">
              Stop trusting screenshots. <span style={{ color: "var(--brand-gold)" }}>Trust the filter.</span>
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-balance text-base text-brand-cream/80 md:text-lg">
              The catalog is free to browse. No card, no broker keys, no autotrading. Just signals that earned the right to reach you.
            </p>
            <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Button
                size="lg"
                asChild
                className="h-12 bg-brand-cream px-6 text-base font-semibold text-emerald-deep hover:bg-brand-cream/90"
              >
                <Link to="/app/catalog">
                  Browse the catalog <ArrowRight className="ml-1.5 size-4" />
                </Link>
              </Button>
              <Button
                size="lg"
                variant="outline"
                asChild
                className="h-12 border-brand-cream/40 bg-transparent px-6 text-base text-brand-cream hover:bg-brand-cream/10 hover:text-brand-cream"
              >
                <Link to="/auth">Create free account</Link>
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="border-t border-border px-6 py-10 md:px-10">
        <div className="mx-auto flex max-w-7xl flex-col gap-6 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <div
              className="grid size-5 place-items-center rounded text-[10px] font-bold text-brand-cream"
              style={{ background: "var(--gradient-emerald)" }}
            >
              B
            </div>
            © {new Date().getFullYear()} Bayn · Signals that survived the filter
          </div>
          <Disclaimer />
        </div>
      </footer>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-sm text-foreground">{value}</div>
      <div className="text-[10px] uppercase text-muted-foreground">{label}</div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-background/50 py-2">
      <div className="text-[10px] uppercase text-muted-foreground">{label}</div>
      <div className="mt-0.5 font-mono text-sm">{value}</div>
    </div>
  );
}

function Bullet({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2 text-muted-foreground">
      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-emerald-glow" />
      <span>{children}</span>
    </li>
  );
}

type Tone = "emerald" | "gold";
type IconType = React.ComponentType<{ className?: string }>;
type CardSpec =
  | { kind: "metric"; title: string; icon: IconType; bigValue: string; bigLabel: string; stats: { label: string; value: string }[] }
  | { kind: "signal"; title: string; icon: IconType }
  | { kind: "equity"; title: string; icon: IconType }
  | { kind: "feature"; title: string; icon: IconType; body: string }
  | { kind: "bullets"; title: string; icon: IconType; bullets: string[] };

function SideColumn({
  tone,
  tag,
  tagIcon: TagIcon,
  title,
  subtitle,
  ctaText,
  ctaTo,
  cards,
}: {
  tone: Tone;
  tag: string;
  tagIcon: IconType;
  title: string;
  subtitle: string;
  ctaText: string;
  ctaTo: string;
  cards: CardSpec[];
}) {
  const accent = tone === "emerald" ? "var(--emerald)" : "var(--brand-gold)";
  const accentGlow = tone === "emerald" ? "var(--emerald-glow)" : "var(--brand-gold)";
  const accentText = tone === "emerald" ? "text-emerald-glow" : "text-brand-gold";

  return (
    <div
      className="flex flex-col gap-4 rounded-3xl border bg-elevated/30 p-5 md:p-6"
      style={{ borderColor: `color-mix(in oklab, ${accent} 28%, var(--border))` }}
    >
      <div>
        <div
          className="mb-4 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider"
          style={{
            background: `color-mix(in oklab, ${accent} 15%, transparent)`,
            color: accentGlow,
            border: `1px solid color-mix(in oklab, ${accent} 35%, transparent)`,
          }}
        >
          <TagIcon className="size-3" /> {tag}
        </div>
        <h3 className="landing-display text-2xl font-semibold tracking-tight md:text-3xl">{title}</h3>
        <p className="mt-2 text-sm text-muted-foreground">{subtitle}</p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {cards.map((c, i) => (
          <SideCard key={i} card={c} tone={tone} />
        ))}
      </div>

      <Link
        to={ctaTo}
        className={`group mt-2 inline-flex items-center justify-between rounded-xl border px-5 py-3.5 text-sm font-medium transition-colors ${accentText}`}
        style={{
          borderColor: `color-mix(in oklab, ${accent} 40%, transparent)`,
          background: `color-mix(in oklab, ${accent} 8%, transparent)`,
        }}
      >
        {ctaText}
        <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" />
      </Link>
    </div>
  );
}

function SideCard({ card, tone }: { card: CardSpec; tone: Tone }) {
  const accent = tone === "emerald" ? "var(--emerald)" : "var(--brand-gold)";
  const accentText = tone === "emerald" ? "text-emerald-glow" : "text-brand-gold";
  const Icon = card.icon;

  return (
    <div className="relative overflow-hidden rounded-xl border border-border/60 bg-background/40 p-4">
      <div className={`mb-3 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider ${accentText}`}>
        <Icon className="size-3" /> {card.title}
      </div>

      {card.kind === "metric" && (
        <>
          <div className="landing-display text-3xl font-bold text-brand-cream">{card.bigValue}</div>
          <div className="mt-1 text-[11px] text-muted-foreground">{card.bigLabel}</div>
          <div className="mt-3 grid grid-cols-3 gap-2 border-t border-border/60 pt-3 text-center">
            {card.stats.map((s) => (
              <Stat key={s.label} label={s.label} value={s.value} />
            ))}
          </div>
        </>
      )}

      {card.kind === "signal" && (
        <>
          <div className="mb-2 flex items-center gap-1.5 text-xs">
            <span className="size-1.5 animate-pulse rounded-full bg-success" />
            <span className="font-mono uppercase text-success">BTC-PERP LONG</span>
            <span className="ml-auto font-mono text-[10px] text-muted-foreground">2m</span>
          </div>
          <div className="text-xs text-muted-foreground">Trend-Following v3</div>
          <div className="mt-3 grid grid-cols-3 gap-1.5 text-center">
            <MiniStat label="Entry" value="67,420" />
            <MiniStat label="Stop" value="65,800" />
            <MiniStat label="Target" value="71,200" />
          </div>
        </>
      )}

      {card.kind === "equity" && (
        <>
          <svg viewBox="0 0 240 70" className="h-16 w-full">
            <defs>
              <linearGradient id={`eq-${tone}`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor={accent} stopOpacity="0.4" />
                <stop offset="100%" stopColor={accent} stopOpacity="0" />
              </linearGradient>
            </defs>
            <path
              d="M0,60 L20,55 L40,58 L60,46 L80,50 L100,38 L120,42 L140,30 L160,34 L180,22 L200,26 L220,14 L240,8 L240,70 L0,70 Z"
              fill={`url(#eq-${tone})`}
            />
            <path
              className="equity-rise"
              d="M0,60 L20,55 L40,58 L60,46 L80,50 L100,38 L120,42 L140,30 L160,34 L180,22 L200,26 L220,14 L240,8"
              fill="none"
              stroke={accent}
              strokeWidth="2"
            />
          </svg>
          <div className="mt-1 text-[11px] text-muted-foreground">Equity · 250 Monte Carlo paths · OOS-clean</div>
        </>
      )}

      {card.kind === "feature" && (
        <p className="text-xs leading-relaxed text-muted-foreground">{card.body}</p>
      )}

      {card.kind === "bullets" && (
        <ul className="space-y-1.5 text-xs text-muted-foreground">
          {card.bullets.map((b) => (
            <li key={b} className="flex items-start gap-2">
              <span
                className="mt-1.5 size-1.5 shrink-0 rounded-full"
                style={{ background: accent }}
              />
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

