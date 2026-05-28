import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  ArrowRight,
  ShieldCheck,
  Sparkles,
  CheckCircle2,
  Search,
  Bell,
  LineChart,
  Wrench,
  Activity,
  TrendingUp,
  Code2,
  GitBranch,
  Lock,
  Cpu,
} from "lucide-react";
import { Disclaimer } from "@/components/common/Disclaimer";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Bayn — Institutional trading, for everyone" },

      {
        name: "description",
        content:
          "Bayn is a marketplace where quants ship backtested strategies and traders follow only the ones that survived. Walk-forward tested, monitored live.",
      },
      { property: "og:title", content: "Bayn — Trading strategies, measured honestly" },
      {
        property: "og:description",
        content:
          "Backtested, out-of-sample, forward-tested. Quants build, traders follow. You stay in control.",
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
      { threshold: 0.12, rootMargin: "0px 0px -60px 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  return (
    <div
      className="min-h-screen bg-background text-foreground"
      style={{ fontFamily: "var(--font-landing-body)" }}
    >
      <style>{`
        .landing-display { font-family: var(--font-landing-display); letter-spacing: -0.025em; }
        .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
        .landing-grad-text {
          background: var(--gradient-gold-emerald);
          -webkit-background-clip: text;
          background-clip: text;
          color: transparent;
        }
        .landing-hero-grad {
          background:
            radial-gradient(ellipse 80% 60% at 50% 0%, color-mix(in oklab, var(--emerald) 22%, transparent), transparent 70%),
            radial-gradient(ellipse 60% 50% at 80% 30%, color-mix(in oklab, var(--brand-gold) 10%, transparent), transparent 70%);
        }
        .surface-card {
          background: var(--elevated);
          border: 1px solid var(--border);
          border-radius: 1.25rem;
          transition: border-color 200ms;
        }
        .surface-card:hover { border-color: color-mix(in oklab, var(--emerald) 45%, transparent); }
        .grid-bg {
          background-image:
            linear-gradient(to right, color-mix(in oklab, var(--foreground) 6%, transparent) 1px, transparent 1px),
            linear-gradient(to bottom, color-mix(in oklab, var(--foreground) 6%, transparent) 1px, transparent 1px);
          background-size: 32px 32px;
          mask-image: radial-gradient(ellipse 80% 60% at 50% 50%, black, transparent);
        }

        /* Reveal */
        [data-reveal] {
          opacity: 0;
          transform: translateY(28px);
          transition: opacity 700ms cubic-bezier(0.22, 1, 0.36, 1),
                      transform 700ms cubic-bezier(0.22, 1, 0.36, 1);
          transition-delay: var(--reveal-delay, 0ms);
        }
        [data-reveal].is-revealed { opacity: 1; transform: translateY(0); }
        @media (prefers-reduced-motion: reduce) {
          [data-reveal] { opacity: 1; transform: none; transition: none; }
          .hero-shimmer, .hero-rise, .equity-draw, .ticker-track { animation: none !important; }
        }

        .hero-rise {
          opacity: 0;
          transform: translateY(20px);
          animation: heroRise 900ms cubic-bezier(0.22, 1, 0.36, 1) forwards;
          animation-delay: var(--rise-delay, 0ms);
        }
        @keyframes heroRise { to { opacity: 1; transform: translateY(0); } }
        .hero-shimmer { background-size: 200% auto; animation: shimmer 6s linear infinite; }
        @keyframes shimmer { 0% { background-position: 0% center; } 100% { background-position: 200% center; } }

        /* Animated nav pill */
        .nav-pill {
          position: absolute;
          background: color-mix(in oklab, var(--background) 35%, transparent);
          backdrop-filter: blur(10px);
          -webkit-backdrop-filter: blur(10px);
          border: 1px solid transparent;
          background-clip: padding-box;
          isolation: isolate;
          overflow: hidden;
          transition: background 300ms, border-color 300ms;

        }
        .nav-pill::before {
          content: "";
          position: absolute;
          inset: -1px;
          border-radius: 9999px;
          padding: 1px;
          background: conic-gradient(
            from var(--nav-angle, 0deg),
            color-mix(in oklab, var(--emerald) 70%, transparent),
            color-mix(in oklab, var(--brand-gold) 70%, transparent),
            color-mix(in oklab, var(--emerald) 70%, transparent)
          );
          -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
          -webkit-mask-composite: xor;
                  mask-composite: exclude;
          animation: navSpin 9s linear infinite;
          z-index: -1;
        }
        @property --nav-angle {
          syntax: '<angle>';
          initial-value: 0deg;
          inherits: false;
        }
        @keyframes navSpin {
          to { --nav-angle: 360deg; }
        }
        .nav-pill::after {
          content: "";
          position: absolute;
          inset: 0;
          border-radius: 9999px;
          background: linear-gradient(
            110deg,
            transparent 35%,
            color-mix(in oklab, var(--foreground) 14%, transparent) 50%,
            transparent 65%
          );
          background-size: 250% 100%;
          animation: navSheen 7s ease-in-out infinite;
          pointer-events: none;
          mix-blend-mode: overlay;
        }
        @keyframes navSheen {
          0% { background-position: 200% 0; }
          100% { background-position: -100% 0; }
        .nav-pill:hover { background: color-mix(in oklab, var(--background) 55%, transparent); }

        .nav-pill:hover { transform: translate(-50%, -1px); }


        .equity-draw { stroke-dasharray: 1200; stroke-dashoffset: 1200; animation: draw 2.8s ease-out forwards; }
        @keyframes draw { to { stroke-dashoffset: 0; } }

        .ticker-track { animation: ticker 38s linear infinite; }
        @keyframes ticker { from { transform: translateX(0); } to { transform: translateX(-50%); } }

        .pulse-dot {
          width: 6px; height: 6px; border-radius: 999px;
          background: var(--success); box-shadow: 0 0 0 0 color-mix(in oklab, var(--success) 60%, transparent);
          animation: pulse 1.6s ease-out infinite;
        }
        @keyframes pulse {
          0% { box-shadow: 0 0 0 0 color-mix(in oklab, var(--success) 60%, transparent); }
          100% { box-shadow: 0 0 0 10px transparent; }
        }
      `}</style>

      {/* HEADER */}
      <header className="sticky top-0 z-30 bg-transparent text-foreground [&_a]:text-foreground">
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

          <nav className="nav-pill landing-display hidden md:flex absolute left-1/2 -translate-x-1/2 items-center gap-1 rounded-full px-3 py-2 text-xs font-medium uppercase tracking-[0.18em] text-foreground/80">
            <a href="#how" className="rounded-full px-4 py-1.5 transition-colors hover:text-foreground">How it works</a>
            <a href="#traders" className="rounded-full px-4 py-1.5 transition-colors hover:text-foreground">For Traders</a>
            <a href="#devs" className="rounded-full px-4 py-1.5 transition-colors hover:text-foreground">For Devs</a>
            <a href="#faq" className="rounded-full px-4 py-1.5 transition-colors hover:text-foreground">FAQ</a>
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
        <div className="absolute inset-0 grid-bg" aria-hidden />
        <div className="relative mx-auto max-w-7xl px-6 pb-20 pt-20 md:px-10 md:pb-24 md:pt-28">
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
              <span className="pulse-dot" />
              <span className="mono font-medium uppercase tracking-wider">127 live strategies · 4,200+ traders</span>
            </div>
            <h1
              className="hero-rise landing-display text-balance text-5xl font-bold leading-[1.04] md:text-7xl"
              style={{ ["--rise-delay" as any]: "100ms" }}
            >
              Institutional trading, <span className="landing-grad-text hero-shimmer">for everyone</span>.

            </h1>
            <p
              className="hero-rise mx-auto mt-7 max-w-2xl text-balance text-lg text-muted-foreground md:text-xl"
              style={{ ["--rise-delay" as any]: "240ms" }}
            >
              Quants ship strategies. We backtest, run out-of-sample, then forward-test them on live markets.
              Traders only ever see what survived.
            </p>
            <div
              className="hero-rise mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row"
              style={{ ["--rise-delay" as any]: "380ms" }}
            >
              <Button
                size="lg"
                asChild
                className="h-12 px-6 text-base text-brand-cream"
                style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}
              >
                <Link to="/app/catalog">
                  <LineChart className="mr-1.5 size-4" /> Browse the catalog
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
                }}
              >
                <Link to="/studio/home">
                  <Wrench className="mr-1.5 size-4" /> Open the Studio
                </Link>
              </Button>
            </div>
          </div>

          {/* Hero chart preview */}
          <div
            className="hero-rise surface-card mt-14 overflow-hidden"
            style={{ ["--rise-delay" as any]: "500ms" }}
          >
            <div className="flex items-center justify-between border-b border-border/60 px-5 py-3 text-xs">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5 mono uppercase tracking-wider text-muted-foreground">
                  <Activity className="size-3.5 text-emerald-glow" /> Trend-Following v3 · BTC-PERP
                </div>
                <span className="hidden md:inline rounded bg-success/15 px-1.5 py-0.5 mono text-[10px] uppercase text-success">Live</span>
              </div>
              <div className="hidden md:flex items-center gap-4 mono text-[11px]">
                <span className="text-muted-foreground">Sharpe <span className="text-foreground">1.84</span></span>
                <span className="text-muted-foreground">Win <span className="text-foreground">58%</span></span>
                <span className="text-muted-foreground">MaxDD <span className="text-danger">−9.2%</span></span>
                <span className="text-muted-foreground">YTD <span className="text-success">+37.4%</span></span>
              </div>
            </div>
            <EquityChart />
            {/* Ticker */}
            <div className="overflow-hidden border-t border-border/60">
              <div className="flex ticker-track" style={{ width: "max-content" }}>
                {[...Array(2)].map((_, dup) => (
                  <div key={dup} className="flex shrink-0 items-center gap-8 px-6 py-2.5 mono text-[11px]">
                    {[
                      { sym: "BTC-PERP", side: "LONG", r: "+2.1R", strat: "Trend v3" },
                      { sym: "SPY", side: "SHORT", r: "+1.4R", strat: "Mean Rev Pro" },
                      { sym: "NVDA", side: "LONG", r: "+0.9R", strat: "Earnings Drift" },
                      { sym: "ES", side: "LONG", r: "+1.8R", strat: "Opening Range" },
                      { sym: "ETH", side: "SHORT", r: "+1.2R", strat: "Funding Skew" },
                      { sym: "AAPL", side: "LONG", r: "+0.6R", strat: "Gap-Fill" },
                      { sym: "QQQ", side: "LONG", r: "+2.4R", strat: "Momentum" },
                    ].map((s, i) => (
                      <div key={`${dup}-${i}`} className="flex items-center gap-2">
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
        </div>
      </section>

      {/* HOW IT WORKS — the filter pipeline */}
      <section id="how" data-reveal className="mx-auto max-w-7xl px-6 py-20 md:px-10 md:py-28">
        <div className="mb-12 text-center">
          <div className="mono mb-3 text-xs uppercase tracking-[0.2em] text-brand-gold">The pipeline</div>
          <h2 className="landing-display mx-auto max-w-3xl text-balance text-3xl font-bold md:text-5xl">
            Every strategy passes a <span className="landing-grad-text">5-stage filter</span> before reaching you.
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-sm text-muted-foreground md:text-base">
            98.5% of submissions are rejected. The ones that survive are monitored live and pulled the moment their edge decays.
          </p>
        </div>

        <div className="surface-card p-6 md:p-8">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {[
              { n: "01", t: "Backtest", v: "8,420", sub: "Rules vs. years of history" },
              { n: "02", t: "Out-of-Sample", v: "2,180", sub: "Held-out data, no peeking" },
              { n: "03", t: "Forward-Test", v: "640", sub: "Paper-traded on live markets" },
              { n: "04", t: "Live Review", v: "210", sub: "Human + walk-forward check" },
              { n: "05", t: "Published", v: "127", sub: "Monitored 24/7" },
            ].map((s, i) => (
              <div
                key={s.n}
                className="relative rounded-xl border border-border/60 p-4"
                style={{ background: `color-mix(in oklab, var(--emerald) ${3 + i * 4}%, transparent)` }}
              >
                <div className="mono text-[10px] text-muted-foreground">{s.n}</div>
                <div className="mt-1 text-sm font-semibold">{s.t}</div>
                <div className="mt-2 mono text-base text-brand-gold">{s.v}</div>
                <div className="mt-1 text-[11px] leading-snug text-muted-foreground">{s.sub}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* DUAL SIDED — TRADERS + DEVS */}
      <section data-reveal className="border-y border-border/60 bg-elevated/40">
        <div className="mx-auto max-w-7xl px-6 py-20 md:px-10 md:py-28">
          <div className="mb-12 text-center">
            <div className="mono mb-3 text-xs uppercase tracking-[0.2em] text-brand-gold">Two sides, one filter</div>
            <h2 className="landing-display mx-auto max-w-3xl text-balance text-3xl font-bold md:text-5xl">
              A marketplace where <span className="landing-grad-text">edge is earned</span>.
            </h2>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* TRADERS */}
            <div
              id="traders"
              className="surface-card relative overflow-hidden p-7 md:p-9"
              style={{ borderColor: "color-mix(in oklab, var(--emerald) 35%, var(--border))" }}
            >
              <div className="mono mb-3 flex items-center gap-2 text-[11px] uppercase tracking-wider text-emerald-glow">
                <LineChart className="size-3.5" /> For traders
              </div>
              <h3 className="landing-display text-2xl font-bold md:text-3xl">Follow strategies that survived.</h3>
              <p className="mt-3 text-sm text-muted-foreground md:text-base">
                Browse a curated catalog. Subscribe to strategies that match your style. Bayn never trades for you — you confirm every order.
              </p>

              <div className="mt-6 grid grid-cols-3 gap-3">
                <Metric label="Avg return · 12mo" value="+37.4%" tone="emerald" />
                <Metric label="Median Sharpe" value="1.84" tone="emerald" />
                <Metric label="Max DD" value="−9%" tone="emerald" />
              </div>

              <ul className="mt-6 space-y-2.5 text-sm">
                <Row icon={Bell}>Real-time signal feed with chart context</Row>
                <Row icon={Lock}>No broker keys. No auto-trading. Ever.</Row>
                <Row icon={Activity}>Track real PnL vs. published backtest</Row>
              </ul>

              <Button
                asChild
                className="mt-7 h-11 w-full text-brand-cream sm:w-auto"
                style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}
              >
                <Link to="/app/catalog">
                  Open the catalog <ArrowRight className="ml-1.5 size-4" />
                </Link>
              </Button>
            </div>

            {/* DEVS */}
            <div
              id="devs"
              className="surface-card relative overflow-hidden p-7 md:p-9"
              style={{ borderColor: "color-mix(in oklab, var(--brand-gold) 35%, var(--border))" }}
            >
              <div className="mono mb-3 flex items-center gap-2 text-[11px] uppercase tracking-wider text-brand-gold">
                <Wrench className="size-3.5" /> For developers
              </div>
              <h3 className="landing-display text-2xl font-bold md:text-3xl">Build your own edge. Trade it yourself.</h3>
              <p className="mt-3 text-sm text-muted-foreground md:text-base">
                Compose strategies in the node builder or describe them in plain English. Backtest, Monte Carlo,
                walk-forward — all built in. Run your own ideas live and keep 100% of the upside.
              </p>

              {/* Faux code snippet */}
              <div className="mono mt-6 overflow-hidden rounded-xl border border-border/60 bg-background/60 p-4 text-[12px] leading-relaxed">
                <div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-wider text-muted-foreground">
                  <Code2 className="size-3" /> strategy.ts
                </div>
                <pre className="overflow-x-auto"><span className="text-emerald-glow">const</span> <span className="text-foreground">signal</span> = <span className="text-foreground">when</span>(
  <span className="text-brand-gold">ema</span>(<span className="text-success">21</span>).<span className="text-brand-gold">crosses</span>(<span className="text-brand-gold">ema</span>(<span className="text-success">55</span>)),
  <span className="text-brand-gold">rsi</span>(<span className="text-success">14</span>) {'>'} <span className="text-success">55</span>,
  <span className="text-brand-gold">vol</span>(<span className="text-success">20</span>) {'<'} <span className="text-success">0.04</span>,
)<span className="text-muted-foreground">;</span>
<span className="text-emerald-glow">deploy</span>(signal, {`{ tf: "1h", mode: "live" }`})<span className="text-muted-foreground">;</span></pre>
              </div>

              <ul className="mt-6 space-y-2.5 text-sm">
                <Row icon={Cpu}>Walk-forward + Monte Carlo built in</Row>
                <Row icon={GitBranch}>Version, fork and A/B your own strategies</Row>
                <Row icon={Sparkles}>AI co-builder: prompt → graph → live</Row>
              </ul>


              <Button
                asChild
                className="mt-7 h-11 w-full sm:w-auto"
                style={{
                  background: "color-mix(in oklab, var(--brand-gold) 22%, transparent)",
                  border: "1px solid color-mix(in oklab, var(--brand-gold) 55%, transparent)",
                  color: "var(--brand-gold)",
                }}
              >
                <Link to="/studio/home">
                  Open the Studio <ArrowRight className="ml-1.5 size-4" />
                </Link>
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* TRUST PILLARS */}
      <section data-reveal className="mx-auto max-w-7xl px-6 py-20 md:px-10 md:py-28">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          {[
            {
              icon: ShieldCheck,
              title: "Tested, not promoted",
              body: "No paid placement. A strategy reaches the catalog only after it clears out-of-sample and forward tests.",
            },
            {
              icon: TrendingUp,
              title: "Live, not historical",
              body: "Signals fire on live market data across stocks, crypto, options and futures — not on cherry-picked screenshots.",
            },
            {
              icon: CheckCircle2,
              title: "You stay in control",
              body: "Bayn never executes for you. Every order needs your confirmation, on your broker, on your terms.",
            },
          ].map(({ icon: Icon, title, body }) => (
            <div key={title} className="surface-card p-7">
              <div
                className="mb-5 grid size-11 place-items-center rounded-lg"
                style={{
                  background: "color-mix(in oklab, var(--emerald) 15%, transparent)",
                  color: "var(--emerald-glow)",
                }}
              >
                <Icon className="size-5" />
              </div>
              <h3 className="landing-display text-lg font-semibold">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" data-reveal className="mx-auto max-w-3xl px-6 pb-20 md:px-10 md:pb-28">
        <div className="mb-10 text-center">
          <div className="mono mb-3 text-xs uppercase tracking-[0.2em] text-brand-gold">Common questions</div>
          <h2 className="landing-display text-balance text-3xl font-bold md:text-4xl">What you'll probably ask first.</h2>
        </div>

        <div className="space-y-3">
          {[
            {
              q: "I'm new to trading. Is this for me?",
              a: "Yes. Each strategy is described in plain language — what it does, when it fires, and its historical track record. You don't need to code or read charts to follow one.",
            },
            {
              q: "Does Bayn trade my money for me?",
              a: "No. We never touch your funds or your broker. We send signals; you decide whether to act on them in your own account.",
            },
            {
              q: "How is performance verified?",
              a: "Every strategy passes backtest, out-of-sample, and forward-test on live data before publication. Live performance is tracked continuously and shown alongside the original backtest.",
            },
            {
              q: "I'm a developer. What's the Studio for?",
              a: "Build your own strategies in a node-based editor or via the AI co-builder. Backtest, run Monte Carlo + walk-forward, then deploy your strategy live and trade it yourself. You keep 100% of the upside — Bayn doesn't take a cut of what you trade.",

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

      {/* FINAL CTA */}
      <section data-reveal className="mx-auto max-w-7xl px-6 pb-24 md:px-10">
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
            <h2 className="landing-display mx-auto max-w-2xl text-balance text-4xl font-bold text-brand-cream md:text-5xl">
              Stop trusting screenshots. <span style={{ color: "var(--brand-gold)" }}>Trust the filter.</span>
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-balance text-base text-brand-cream/80 md:text-lg">
              Free to browse. No card, no broker keys. Just strategies that earned the right to reach you.
            </p>
            <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Button
                size="lg"
                asChild
                className="h-12 bg-brand-cream px-6 text-base font-semibold text-emerald-deep hover:bg-brand-cream/90"
              >
                <Link to="/app/catalog">
                  <Search className="mr-1.5 size-4" /> Browse the catalog
                </Link>
              </Button>
              <Button
                size="lg"
                variant="outline"
                asChild
                className="h-12 border-brand-cream/40 bg-transparent px-6 text-base text-brand-cream hover:bg-brand-cream/10 hover:text-brand-cream"
              >
                <Link to="/studio/home">Build a strategy</Link>
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
            © {new Date().getFullYear()} Bayn · Strategies that survived the filter
          </div>
          <Disclaimer />
        </div>
      </footer>
    </div>
  );
}

/* === Subcomponents === */

function Row({ icon: Icon, children }: { icon: React.ComponentType<{ className?: string }>; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2.5 text-muted-foreground">
      <Icon className="mt-0.5 size-4 shrink-0 text-foreground/70" />
      <span><span className="text-foreground">{children}</span></span>
    </li>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone: "emerald" | "gold" }) {
  const color = tone === "emerald" ? "var(--emerald-glow)" : "var(--brand-gold)";
  return (
    <div className="rounded-lg border border-border/60 bg-background/50 p-3">
      <div className="mono text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="landing-display mt-1 text-lg font-bold" style={{ color }}>{value}</div>
    </div>
  );
}

function EquityChart() {
  // Generated curve points (monotonic upward with realistic noise)
  const points = [
    [0, 180], [40, 172], [80, 168], [120, 158], [160, 162], [200, 150],
    [240, 140], [280, 145], [320, 130], [360, 118], [400, 122], [440, 108],
    [480, 96], [520, 100], [560, 88], [600, 74], [640, 78], [680, 64],
    [720, 56], [760, 60], [800, 48], [840, 38], [880, 42], [920, 30], [960, 22],
  ];
  const path = points.map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`)).join(" ");
  const area = `${path} L960,200 L0,200 Z`;
  return (
    <div className="relative h-[200px] w-full bg-background/40">
      <svg viewBox="0 0 960 200" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
        <defs>
          <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--emerald-glow)" stopOpacity="0.32" />
            <stop offset="100%" stopColor="var(--emerald-glow)" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="eqStroke" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--emerald)" />
            <stop offset="100%" stopColor="var(--brand-gold)" />
          </linearGradient>
        </defs>
        {/* gridlines */}
        {[40, 80, 120, 160].map((y) => (
          <line key={y} x1="0" y1={y} x2="960" y2={y}
            stroke="color-mix(in oklab, var(--foreground) 6%, transparent)" strokeDasharray="2 4" />
        ))}
        <path d={area} fill="url(#eqFill)" />
        <path d={path} fill="none" stroke="url(#eqStroke)" strokeWidth="2.5"
          strokeLinecap="round" strokeLinejoin="round" className="equity-draw" />
        {/* end dot */}
        <circle cx="960" cy="22" r="4" fill="var(--brand-gold)" />
      </svg>
    </div>
  );
}
