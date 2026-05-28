import { createFileRoute, Link } from "@tanstack/react-router";
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
      `}</style>

      {/* HEADER */}
      <header className="sticky top-0 z-30 border-b border-border/60 bg-background/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 md:px-10">
          <Link to="/" className="flex items-center gap-2.5 text-base font-semibold">
            <div
              className="grid size-8 place-items-center rounded-lg font-bold text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}
            >
              B
            </div>
            <span className="landing-display tracking-tight">Bayn</span>
          </Link>
          <nav className="hidden items-center gap-7 text-sm text-muted-foreground md:flex">
            <a href="#pipeline" className="transition-colors hover:text-foreground">The filter</a>
            <a href="#catalog" className="transition-colors hover:text-foreground">Catalog</a>
            <a href="#studio" className="transition-colors hover:text-foreground">Studio</a>
            <a href="#proof" className="transition-colors hover:text-foreground">Proof</a>
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
              className="mx-auto mb-7 inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs"
              style={{
                borderColor: "color-mix(in oklab, var(--brand-gold) 40%, transparent)",
                background: "color-mix(in oklab, var(--brand-gold) 10%, transparent)",
                color: "var(--brand-gold)",
              }}
            >
              <BadgeCheck className="size-3.5" />
              <span className="font-medium">A two-sided market for verified trading edge</span>
            </div>
            <h1 className="landing-display text-balance text-5xl font-bold leading-[1.05] md:text-7xl lg:text-[5.5rem]">
              <span className="landing-grad-text">Trade</span> the signal.{" "}
              <span className="landing-grad-text">Build</span> the signal.
            </h1>
            <p className="mx-auto mt-7 max-w-2xl text-balance text-lg text-muted-foreground md:text-xl">
              Bayn is the marketplace where quants ship verified strategies and traders follow them.
              <span className="text-foreground"> One filter. Both sides win.</span>
            </p>
            <div className="mt-9 grid gap-3 sm:grid-cols-2 sm:gap-4">
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
            <div className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
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

      {/* BENTO GRID */}
      <section id="pipeline" className="mx-auto max-w-7xl px-6 pb-20 pt-10 md:px-10 md:pb-32">
        <div className="mb-10 flex flex-col items-start justify-between gap-4 md:flex-row md:items-end">
          <div>
            <div className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-brand-gold">The platform</div>
            <h2 className="landing-display max-w-2xl text-3xl font-bold tracking-tight md:text-5xl">
              Built so you can <span className="landing-grad-text">trust the signal</span>.
            </h2>
          </div>
          <p className="max-w-md text-sm text-muted-foreground">
            Most signal services optimize for marketing. We optimize for measured survival —
            then put you in the driver's seat.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-6 md:auto-rows-[minmax(180px,auto)]">
          {/* Pipeline visualization — large */}
          <div className="landing-bento-card landing-glow-emerald md:col-span-4 md:row-span-2">
            <div className="relative z-10 flex h-full flex-col p-7">
              <div className="mb-4 flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-emerald-glow">
                <Filter className="size-3.5" /> The 5-stage filter
              </div>
              <h3 className="landing-display text-2xl font-semibold md:text-3xl">
                Every strategy clears five gates. Most never make it.
              </h3>
              <div className="mt-6 grid grid-cols-5 gap-2">
                {[
                  { n: "01", t: "Backtest", v: "8,420" },
                  { n: "02", t: "Out-of-Sample", v: "2,180" },
                  { n: "03", t: "Forward-Test", v: "640" },
                  { n: "04", t: "Live Review", v: "210" },
                  { n: "05", t: "Published", v: "127" },
                ].map((s, i) => (
                  <div
                    key={s.n}
                    className="rounded-lg border border-border/60 p-3"
                    style={{
                      background: `color-mix(in oklab, var(--emerald) ${4 + i * 4}%, transparent)`,
                    }}
                  >
                    <div className="font-mono text-[10px] text-muted-foreground">{s.n}</div>
                    <div className="mt-1 text-xs font-medium">{s.t}</div>
                    <div className="mt-2 font-mono text-sm text-brand-gold">{s.v}</div>
                  </div>
                ))}
              </div>
              <div className="mt-auto flex items-end justify-between gap-4 pt-6">
                <p className="text-sm text-muted-foreground">
                  98.5% of strategies are rejected. The rest are continuously monitored — pulled the moment edge decays.
                </p>
                <Button variant="ghost" size="sm" asChild>
                  <Link to="/app/catalog" className="text-emerald-glow">
                    See the catalog <ArrowRight className="ml-1 size-3.5" />
                  </Link>
                </Button>
              </div>
            </div>
          </div>

          {/* Stats card */}
          <div className="landing-bento-card md:col-span-2">
            <div className="flex h-full flex-col justify-between p-6">
              <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-brand-gold">
                <TrendingUp className="size-3.5" /> Live performance
              </div>
              <div>
                <div className="landing-display text-5xl font-bold text-brand-cream">
                  +37.4<span className="text-2xl text-brand-gold">%</span>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">Avg published-strategy return · trailing 12mo</div>
              </div>
              <div className="grid grid-cols-3 gap-3 border-t border-border/60 pt-4 text-center">
                <Stat label="Sharpe" value="1.84" />
                <Stat label="Win rate" value="58%" />
                <Stat label="Max DD" value="−9%" />
              </div>
            </div>
          </div>

          {/* You stay in control */}
          <div className="landing-bento-card md:col-span-2">
            <div className="flex h-full flex-col p-6">
              <Lock className="mb-3 size-5 text-emerald-glow" />
              <h3 className="landing-display text-lg font-semibold">You stay in control</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Bayn never executes a single trade for you. Every signal is yours to confirm — or skip — through your broker.
              </p>
              <div
                className="mt-auto rounded-lg border px-3 py-2 text-[11px] text-muted-foreground"
                style={{
                  borderColor: "color-mix(in oklab, var(--emerald) 25%, transparent)",
                  background: "color-mix(in oklab, var(--emerald) 6%, transparent)",
                }}
              >
                Zero broker keys required to browse.
              </div>
            </div>
          </div>

          {/* Equity chart card */}
          <div className="landing-bento-card landing-glow-gold md:col-span-2">
            <div className="relative z-10 flex h-full flex-col p-6">
              <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-brand-gold">
                <Activity className="size-3.5" /> Verified track record
              </div>
              <h3 className="landing-display mt-2 text-lg font-semibold">Every claim is auditable.</h3>
              <svg viewBox="0 0 240 80" className="mt-3 h-20 w-full">
                <defs>
                  <linearGradient id="eq" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="var(--brand-gold)" stopOpacity="0.4" />
                    <stop offset="100%" stopColor="var(--brand-gold)" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <path
                  d="M0,70 L20,60 L40,62 L60,48 L80,52 L100,38 L120,42 L140,28 L160,32 L180,20 L200,24 L220,12 L240,8 L240,80 L0,80 Z"
                  fill="url(#eq)"
                />
                <path
                  className="equity-rise"
                  d="M0,70 L20,60 L40,62 L60,48 L80,52 L100,38 L120,42 L140,28 L160,32 L180,20 L200,24 L220,12 L240,8"
                  fill="none"
                  stroke="var(--brand-gold)"
                  strokeWidth="2"
                />
              </svg>
              <div className="mt-2 text-xs text-muted-foreground">Equity curve · sample strategy · last 12 months</div>
            </div>
          </div>

          {/* Signal preview */}
          <div className="landing-bento-card md:col-span-2">
            <div className="flex h-full flex-col p-6">
              <div className="mb-2 flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-xs">
                  <span className="size-1.5 animate-pulse rounded-full bg-success" />
                  <span className="font-mono uppercase text-success">Just fired</span>
                </span>
                <span className="font-mono text-[10px] text-muted-foreground">2m ago</span>
              </div>
              <div className="landing-display text-xl font-semibold">BTC-PERP · LONG</div>
              <div className="mt-1 text-xs text-muted-foreground">Trend-Following v3 · Crypto</div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                <MiniStat label="Entry" value="67,420" />
                <MiniStat label="Stop" value="65,800" />
                <MiniStat label="Target" value="71,200" />
              </div>
              <Button asChild variant="outline" size="sm" className="mt-auto justify-between">
                <Link to="/app/signals">
                  Open signal feed <ArrowRight className="size-3.5" />
                </Link>
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* TWO-SIDED CTA */}
      <section id="catalog" className="mx-auto max-w-7xl px-6 pb-24 md:px-10">
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          {/* Trader */}
          <Link
            to="/app/catalog"
            className="group relative overflow-hidden rounded-2xl border border-border bg-elevated p-8 transition-all hover:-translate-y-0.5"
            style={{
              borderColor: "color-mix(in oklab, var(--emerald) 30%, var(--border))",
            }}
          >
            <div
              className="pointer-events-none absolute inset-0 opacity-50"
              style={{
                background:
                  "radial-gradient(circle at 80% 0%, color-mix(in oklab, var(--emerald-glow) 20%, transparent), transparent 60%)",
              }}
            />
            <div className="relative">
              <div
                className="mb-5 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider"
                style={{
                  background: "color-mix(in oklab, var(--emerald) 15%, transparent)",
                  color: "var(--emerald-glow)",
                  border: "1px solid color-mix(in oklab, var(--emerald) 35%, transparent)",
                }}
              >
                <LineChart className="size-3" /> For traders
              </div>
              <h3 className="landing-display text-3xl font-semibold tracking-tight">Follow verified signals</h3>
              <p className="mt-3 text-sm text-muted-foreground md:text-base">
                Browse a curated catalog. Subscribe to the strategies that fit your style. Receive signals the moment they fire — confirm and route through your broker.
              </p>
              <ul className="mt-5 space-y-2 text-sm">
                <Bullet>Free catalog access · no card required</Bullet>
                <Bullet>Mobile-first signal feed with chart context</Bullet>
                <Bullet>Track your real PnL vs. the published backtest</Bullet>
              </ul>
              <div className="mt-7 inline-flex items-center gap-1.5 text-sm font-medium text-emerald-glow group-hover:gap-2.5">
                Enter the trader app <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" />
              </div>
            </div>
          </Link>

          {/* Studio */}
          <Link
            id="studio"
            to="/studio/home"
            className="group relative overflow-hidden rounded-2xl border border-border bg-elevated p-8 transition-all hover:-translate-y-0.5"
            style={{
              borderColor: "color-mix(in oklab, var(--brand-gold) 30%, var(--border))",
            }}
          >
            <div
              className="pointer-events-none absolute inset-0 opacity-50"
              style={{
                background:
                  "radial-gradient(circle at 80% 0%, color-mix(in oklab, var(--brand-gold) 20%, transparent), transparent 60%)",
              }}
            />
            <div className="relative">
              <div
                className="mb-5 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider"
                style={{
                  background: "color-mix(in oklab, var(--brand-gold) 14%, transparent)",
                  color: "var(--brand-gold)",
                  border: "1px solid color-mix(in oklab, var(--brand-gold) 35%, transparent)",
                }}
              >
                <Sparkles className="size-3" /> For developers
              </div>
              <h3 className="landing-display text-3xl font-semibold tracking-tight">Build in the Studio</h3>
              <p className="mt-3 text-sm text-muted-foreground md:text-base">
                Compose strategies with a node-based builder or describe them in plain English. Backtest, run out-of-sample, forward-test, submit. Earn revenue share when accepted.
              </p>
              <ul className="mt-5 space-y-2 text-sm">
                <Bullet>AI builder turns prose into a graph</Bullet>
                <Bullet>Monte Carlo + walk-forward built in</Bullet>
                <Bullet>Get paid when traders subscribe</Bullet>
              </ul>
              <div className="mt-7 inline-flex items-center gap-1.5 text-sm font-medium text-brand-gold group-hover:gap-2.5">
                Open the Studio <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" />
              </div>
            </div>
          </Link>
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
