import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  ArrowRight,
  ShieldCheck,
  Eye,
  Sparkles,
  CheckCircle2,
  Search,
  Bell,
} from "lucide-react";
import { Disclaimer } from "@/components/common/Disclaimer";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Bayn — Trading ideas you can actually trust" },
      {
        name: "description",
        content:
          "Bayn is a simple way to discover trading ideas built by experts and tested before you ever see them. Free to browse. You stay in control.",
      },
      { property: "og:title", content: "Bayn — Trading ideas you can actually trust" },
      {
        property: "og:description",
        content:
          "Browse trading ideas built by experts and tested before they reach you. Free to start. You confirm every trade.",
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

        /* Scroll reveal */
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
          .hero-shimmer, .hero-rise { animation: none !important; }
        }

        .hero-rise {
          opacity: 0;
          transform: translateY(20px);
          animation: heroRise 900ms cubic-bezier(0.22, 1, 0.36, 1) forwards;
          animation-delay: var(--rise-delay, 0ms);
        }
        @keyframes heroRise { to { opacity: 1; transform: translateY(0); } }
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

          <nav className="landing-display hidden md:flex absolute left-1/2 -translate-x-1/2 items-center gap-1 rounded-full border border-foreground/25 bg-transparent px-3 py-2 text-xs font-medium uppercase tracking-[0.18em] text-foreground/80">
            <a href="#how" className="rounded-full px-4 py-1.5 transition-colors hover:text-foreground">How it works</a>
            <a href="#why" className="rounded-full px-4 py-1.5 transition-colors hover:text-foreground">Why Bayn</a>
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
        <div className="mx-auto max-w-4xl px-6 pb-20 pt-24 text-center md:px-10 md:pb-28 md:pt-32">
          <h1
            className="hero-rise landing-display text-balance text-5xl font-bold leading-[1.05] md:text-7xl"
            style={{ ["--rise-delay" as any]: "60ms" }}
          >
            Trading ideas you can <span className="landing-grad-text hero-shimmer">actually trust</span>.
          </h1>
          <p
            className="hero-rise mx-auto mt-7 max-w-2xl text-balance text-lg text-muted-foreground md:text-xl"
            style={{ ["--rise-delay" as any]: "220ms" }}
          >
            Bayn is a simple place to discover trading ideas. Experts build them, we test them, and only the
            ones that actually work reach you.
          </p>
          <div
            className="hero-rise mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row"
            style={{ ["--rise-delay" as any]: "360ms" }}
          >
            <Button
              size="lg"
              asChild
              className="h-12 px-7 text-base text-brand-cream"
              style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}
            >
              <Link to="/app/catalog">
                Browse ideas — it's free <ArrowRight className="ml-1.5 size-4" />
              </Link>
            </Button>
            <Button size="lg" variant="ghost" asChild className="h-12 px-5 text-base">
              <a href="#how">See how it works</a>
            </Button>
          </div>
          <p
            className="hero-rise mt-6 text-xs text-muted-foreground"
            style={{ ["--rise-delay" as any]: "480ms" }}
          >
            No credit card. No connecting your bank. You always decide what to do.
          </p>
        </div>
      </section>

      {/* HOW IT WORKS — three plain steps */}
      <section id="how" data-reveal className="mx-auto max-w-6xl px-6 py-20 md:px-10 md:py-28">
        <div className="mb-12 text-center">
          <div className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-brand-gold">How it works</div>
          <h2 className="landing-display mx-auto max-w-2xl text-balance text-3xl font-bold md:text-5xl">
            Three steps. <span className="landing-grad-text">No jargon.</span>
          </h2>
        </div>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          {[
            {
              n: "1",
              icon: Sparkles,
              title: "Experts build ideas",
              body: "Quants and developers create trading strategies — clear rules for when to buy and when to sell.",
            },
            {
              n: "2",
              icon: ShieldCheck,
              title: "We test them honestly",
              body: "Every idea has to prove it works on past data and on live markets before we ever publish it. Most don't make it.",
            },
            {
              n: "3",
              icon: Bell,
              title: "You get a simple alert",
              body: "When an idea you're following sees an opportunity, we send a clear notification. You decide whether to act on it.",
            },
          ].map(({ n, icon: Icon, title, body }) => (
            <div key={n} className="relative rounded-2xl border border-border bg-elevated p-7">
              <div
                className="landing-display absolute right-5 top-4 text-5xl font-bold opacity-10"
                aria-hidden
              >
                {n}
              </div>
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

      {/* WHY BAYN — three plain promises */}
      <section id="why" data-reveal className="border-y border-border/60 bg-elevated/40">
        <div className="mx-auto max-w-6xl px-6 py-20 md:px-10 md:py-28">
          <div className="mb-12 text-center">
            <div className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-brand-gold">Why Bayn</div>
            <h2 className="landing-display mx-auto max-w-2xl text-balance text-3xl font-bold md:text-5xl">
              Built for people who <span className="landing-grad-text">don't trust hype</span>.
            </h2>
          </div>

          <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
            {[
              {
                icon: ShieldCheck,
                title: "Tested, not promoted",
                body: "We don't take anyone's word for it. Every idea has to prove itself with real numbers before it reaches you.",
              },
              {
                icon: Eye,
                title: "Honest results",
                body: "You see the wins and the losses. No cherry-picked screenshots — just the real track record of each idea.",
              },
              {
                icon: CheckCircle2,
                title: "You stay in control",
                body: "Bayn never trades for you. We send you ideas, you decide what to do. Nothing happens without your say-so.",
              },
            ].map(({ icon: Icon, title, body }) => (
              <div key={title} className="rounded-2xl border border-border bg-background p-7">
                <div
                  className="mb-5 grid size-11 place-items-center rounded-lg"
                  style={{
                    background: "color-mix(in oklab, var(--brand-gold) 18%, transparent)",
                    color: "var(--brand-gold)",
                  }}
                >
                  <Icon className="size-5" />
                </div>
                <h3 className="landing-display text-lg font-semibold">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FAQ — answer the obvious questions in plain English */}
      <section id="faq" data-reveal className="mx-auto max-w-3xl px-6 py-20 md:px-10 md:py-28">
        <div className="mb-10 text-center">
          <div className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-brand-gold">Common questions</div>
          <h2 className="landing-display text-balance text-3xl font-bold md:text-4xl">
            Wait, what exactly is Bayn?
          </h2>
        </div>

        <div className="space-y-4">
          {[
            {
              q: "I don't know much about the stock market. Is this for me?",
              a: "Yes. You don't need to know how to build a strategy or read a chart. Bayn shows you ideas in plain language — what it does, how often it works, and what could go wrong.",
            },
            {
              q: "Does Bayn trade my money for me?",
              a: "No. We never touch your money or your account. We send you an idea; you decide whether to follow it through your own broker.",
            },
            {
              q: "Does it cost anything?",
              a: "Browsing the catalog is free. No credit card to sign up. Some ideas have a small subscription if you want their live alerts.",
            },
            {
              q: "How do I know the ideas actually work?",
              a: "We only publish ideas that have passed multiple rounds of testing on real market data. We also show the live results — including losses — so you can judge for yourself.",
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
              Start with ideas that <span style={{ color: "var(--brand-gold)" }}>earned your trust</span>.
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-balance text-base text-brand-cream/80 md:text-lg">
              Free to browse. No card, no account hookups. Just clear ideas, in plain English.
            </p>
            <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Button
                size="lg"
                asChild
                className="h-12 bg-brand-cream px-6 text-base font-semibold text-emerald-deep hover:bg-brand-cream/90"
              >
                <Link to="/app/catalog">
                  <Search className="mr-1.5 size-4" /> Browse ideas
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
            © {new Date().getFullYear()} Bayn · Trading ideas you can trust
          </div>
          <Disclaimer />
        </div>
      </footer>
    </div>
  );
}
