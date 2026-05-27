import { createFileRoute, Link } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { BadgeCheck, ShieldCheck, Activity, ArrowRight } from "lucide-react";
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
          <div className="grid size-7 place-items-center rounded-md bg-cyan/15 text-cyan font-bold">B</div>
          Bayn
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" asChild><Link to="/auth">Sign in</Link></Button>
          <Button asChild className="bg-cyan text-cyan-foreground hover:bg-cyan/90">
            <Link to="/app/catalog">See the catalog</Link>
          </Button>
        </div>
      </header>

      <section className="mx-auto max-w-5xl px-6 pb-20 pt-16 text-center md:pt-28">
        <div className="mx-auto mb-6 inline-flex items-center gap-2 rounded-full border border-gold/30 bg-gold/10 px-3 py-1 text-xs text-gold">
          <BadgeCheck className="size-3.5" /> Edge-verified strategies only
        </div>
        <h1 className="text-balance text-5xl font-semibold tracking-tight md:text-7xl">
          Signals that <span className="text-cyan">survived the filter</span>.
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-balance text-lg text-muted-foreground md:text-xl">
          Every strategy in Bayn passes a 5-stage pipeline before a single signal reaches you:
          backtest → out-of-sample → forward-test → live → human review.
          The filtering is the product.
        </p>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
          <Button size="lg" asChild className="bg-cyan text-cyan-foreground hover:bg-cyan/90">
            <Link to="/app/catalog">See the catalog <ArrowRight className="ml-2 size-4" /></Link>
          </Button>
          <Button size="lg" variant="outline" asChild>
            <Link to="/auth">Create account</Link>
          </Button>
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
            <div className="grid size-5 place-items-center rounded bg-cyan/15 text-cyan text-[10px] font-bold">B</div>
            © {new Date().getFullYear()} Bayn
          </div>
          <Disclaimer />
        </div>
      </footer>
    </div>
  );
}
