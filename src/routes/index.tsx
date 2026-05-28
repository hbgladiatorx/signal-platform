import { createFileRoute, Link } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { BadgeCheck, ShieldCheck, Activity, ArrowRight, LineChart, Wrench } from "lucide-react";
import { Disclaimer } from "@/components/common/Disclaimer";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Bayn — Signals that survived the filter" },
      { name: "description", content: "Bayn publishes only trading strategies that survive a 5-stage edge pipeline: backtest, out-of-sample, forward-test, live review, and continuous monitoring." },
      { property: "og:title", content: "Bayn — Signals that survived the filter" },
      { property: "og:description", content: "A curated catalog of trading strategies that have been measured honestly. Stocks, crypto, options, futures." },
    ],
  }),
  component: Landing,
});

function Landing() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-between px-6 py-5 md:px-12">
        <div className="flex items-center gap-2 text-lg font-semibold">
          <div className="grid size-7 place-items-center rounded-md bg-cyan/15 font-bold text-cyan">B</div>
          Bayn
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" asChild><Link to="/auth">Sign in</Link></Button>
          <Button asChild className="bg-cyan text-cyan-foreground hover:bg-cyan/90">
            <Link to="/app/catalog">See the catalog</Link>
          </Button>
        </div>
      </header>

      <section className="mx-auto max-w-5xl px-6 pb-12 pt-16 text-center md:pt-24">
        <div className="mx-auto mb-6 inline-flex items-center gap-2 rounded-full border border-gold/30 bg-gold/10 px-3 py-1 text-xs text-gold">
          <BadgeCheck className="size-3.5" /> Edge-verified strategies only
        </div>
        <h1 className="text-balance text-5xl font-semibold tracking-tight md:text-7xl">
          Signals that <span className="text-cyan">survived the filter</span>.
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-balance text-lg text-muted-foreground md:text-xl">
          Every strategy in Bayn passes a 5-stage pipeline before a single signal reaches you:
          backtest → out-of-sample → forward-test → live → human review.
        </p>
      </section>

      {/* Two-sided entry — Trader vs Developer */}
      <section className="mx-auto max-w-5xl px-6 pb-20">
        <div className="mb-4 text-center text-xs font-mono uppercase tracking-[0.2em] text-muted-foreground">
          Choose your side
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Link
            to="/app/catalog"
            className="group relative overflow-hidden rounded-2xl border border-border bg-elevated p-7 transition hover:border-cyan/50"
          >
            <div className="absolute inset-x-0 top-0 h-1 bg-cyan" />
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-cyan/30 bg-cyan/10 px-2.5 py-0.5 text-[10px] font-mono uppercase tracking-wider text-cyan">
              <LineChart className="size-3" /> For Traders
            </div>
            <h2 className="text-2xl font-semibold tracking-tight">Follow verified signals</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Browse a curated catalog, follow strategies, and act on live signals. Bayn never trades your account — every order is yours to confirm.
            </p>
            <div className="mt-5 inline-flex items-center gap-1 text-sm font-medium text-cyan group-hover:gap-2">
              Enter the trader app <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" />
            </div>
          </Link>

          <Link
            to="/studio/home"
            className="group relative overflow-hidden rounded-2xl border border-border bg-elevated p-7 transition hover:border-violet/50"
          >
            <div className="absolute inset-x-0 top-0 h-1 bg-violet" />
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-violet/30 bg-violet/10 px-2.5 py-0.5 text-[10px] font-mono uppercase tracking-wider text-violet">
              <Wrench className="size-3" /> For Developers
            </div>
            <h2 className="text-2xl font-semibold tracking-tight">Build strategies in the Studio</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Compose strategies with a node-based builder, backtest, forward-test, and submit to the pipeline. Earn revenue share when accepted.
            </p>
            <div className="mt-5 inline-flex items-center gap-1 text-sm font-medium text-violet group-hover:gap-2">
              Open the Studio <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" />
            </div>
          </Link>
        </div>
      </section>

      <section className="mx-auto grid max-w-6xl grid-cols-1 gap-4 px-6 pb-24 md:grid-cols-3">
        {[
          { icon: ShieldCheck, title: "Verified, not promoted",
            body: "We don't take a strategy's word for it. Every published strategy has cleared an out-of-sample test and a live forward-test before it reaches the catalog." },
          { icon: Activity, title: "Live, not historical",
            body: "Signals are derived from rules running on live market data — across stocks, crypto, options, and futures. You see them the moment they fire." },
          { icon: BadgeCheck, title: "You're still the trader",
            body: "Bayn never trades your account automatically. Every order requires your confirmation. We measure outcomes honestly so you can decide what to follow." },
        ].map(({ icon: Icon, title, body }) => (
          <div key={title} className="rounded-2xl border border-border bg-elevated p-6">
            <Icon className="mb-4 size-5 text-cyan" />
            <h3 className="text-lg font-semibold">{title}</h3>
            <p className="mt-2 text-sm text-muted-foreground">{body}</p>
          </div>
        ))}
      </section>

      <footer className="border-t border-border px-6 py-10 md:px-12">
        <div className="mx-auto flex max-w-6xl flex-col gap-6 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <div className="grid size-5 place-items-center rounded bg-cyan/15 text-[10px] font-bold text-cyan">B</div>
            © {new Date().getFullYear()} Bayn
          </div>
          <Disclaimer />
        </div>
      </footer>
    </div>
  );
}
