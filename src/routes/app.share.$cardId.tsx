import { createFileRoute, Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Disclaimer } from "@/components/common/Disclaimer";
import { TradeShareCard } from "@/components/common/TradeShareCard";
import { getSignalById, getUserPerformance } from "@/lib/api";
import { Share2, ArrowLeft, Twitter, Linkedin, Link2 } from "lucide-react";
import { toast } from "sonner";
import { Area, AreaChart, ResponsiveContainer } from "recharts";

export const Route = createFileRoute("/app/share/$cardId")({
  head: ({ params }) => ({
    meta: [
      { title: `Bayn — verified trade · ${params.cardId}` },
      { property: "og:title", content: "Bayn — verified trade card" },
      { property: "og:description", content: "A trade signal verified by the Bayn 5-stage edge pipeline." },
    ],
  }),
  component: SharePage,
});

function SharePage() {
  const { cardId } = useParams({ from: "/app/share/$cardId" });
  const isSignal = cardId.startsWith("sig-");

  return (
    <div className="min-h-screen bg-background px-4 py-10">
      <div className="mx-auto flex max-w-5xl flex-col items-center gap-6">
        <div className="flex w-full items-center justify-between">
          <Button asChild variant="ghost" size="sm">
            <Link to="/app/home"><ArrowLeft className="mr-1 size-3.5" /> Back</Link>
          </Button>
          <ShareActions />
        </div>

        {isSignal ? <SignalCard id={cardId} /> : <PerformanceCard cardId={cardId} />}

        <p className="max-w-md text-center text-xs text-muted-foreground">
          This card is a static, shareable snapshot. Anyone with the link can view it.
        </p>
      </div>
    </div>
  );
}

function SignalCard({ id }: { id: string }) {
  const { data: s, isFetched } = useQuery({ queryKey: ["share-sig", id], queryFn: () => getSignalById(id) });
  if (!s && isFetched) {
    return <Card className="border-border bg-elevated p-8 text-muted-foreground">Trade not found.</Card>;
  }
  if (!s) return <Card className="h-96 w-full max-w-md animate-pulse border-border bg-elevated" />;
  return <TradeShareCard signal={s} strategyName={s.strategyName} />;
}

function PerformanceCard({ cardId }: { cardId: string }) {
  const days = Number(cardId.replace(/^\D+/, "")) || 30;
  const { data } = useQuery({ queryKey: ["share-perf", days], queryFn: () => getUserPerformance(days) });
  const start = data?.equity[0]?.equity ?? 10000;
  const end = data?.equity[data.equity.length - 1]?.equity ?? 10000;
  const ret = (end - start) / start;

  return (
    <Card
      className="w-full max-w-md overflow-hidden border-border bg-elevated"
      style={{
        backgroundImage:
          "radial-gradient(900px 240px at 100% -20%, color-mix(in oklab, var(--cyan) 14%, transparent), transparent 60%), radial-gradient(700px 220px at -10% 110%, color-mix(in oklab, var(--violet) 12%, transparent), transparent 60%)",
      }}
    >
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-2 text-sm">
          <div className="grid size-6 place-items-center rounded bg-cyan/15 text-[11px] font-bold text-cyan">B</div>
          <span className="font-semibold">Bayn</span>
          <span className="text-xs text-muted-foreground">· verified track record</span>
        </div>
        <span className="rounded-full border border-cyan/40 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-cyan">
          Last {days}d
        </span>
      </div>
      <div className="space-y-5 px-6 py-6">
        <div>
          <div className="text-xs uppercase tracking-wider text-muted-foreground">Return</div>
          <div className={`mt-1 font-mono text-4xl ${ret >= 0 ? "text-cyan" : "text-danger"}`}>
            {ret >= 0 ? "+" : ""}{(ret * 100).toFixed(2)}%
          </div>
        </div>
        <div className="h-28 rounded-lg border border-border bg-background/40 p-1">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data?.equity ?? []}>
              <defs>
                <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--cyan)" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="var(--cyan)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area type="monotone" dataKey="equity" stroke="var(--cyan)" strokeWidth={2} fill="url(#sg)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="grid grid-cols-3 gap-3 border-t border-border pt-4 text-center">
          <div>
            <div className="font-mono">{data?.kpis.totalTaken ?? "—"}</div>
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Signals</div>
          </div>
          <div>
            <div className="font-mono">{data ? `${(data.kpis.winRate * 100).toFixed(0)}%` : "—"}</div>
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Win rate</div>
          </div>
          <div>
            <div className="font-mono">{data ? `${data.kpis.avgR.toFixed(2)}R` : "—"}</div>
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Avg R</div>
          </div>
        </div>
        <Disclaimer variant="card" />
      </div>
      <div className="flex items-center justify-between border-t border-border bg-background/40 px-6 py-3">
        <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">Powered by</span>
        <span className="font-semibold tracking-tight">Bayn<span className="ml-1 text-cyan">·</span> bayn.app</span>
      </div>
    </Card>
  );
}

function ShareActions() {
  const url = typeof window !== "undefined" ? window.location.href : "";
  const text = encodeURIComponent("My verified trade on Bayn —");
  return (
    <div className="flex items-center gap-1">
      <Button variant="outline" size="sm" onClick={() => { navigator.clipboard?.writeText(url); toast.success("Link copied"); }}>
        <Link2 className="mr-1.5 size-3.5" /> Copy link
      </Button>
      <Button asChild variant="ghost" size="icon">
        <a href={`https://twitter.com/intent/tweet?text=${text}&url=${encodeURIComponent(url)}`} target="_blank" rel="noreferrer" aria-label="Share on X">
          <Twitter className="size-4" />
        </a>
      </Button>
      <Button asChild variant="ghost" size="icon">
        <a href={`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`} target="_blank" rel="noreferrer" aria-label="Share on LinkedIn">
          <Linkedin className="size-4" />
        </a>
      </Button>
      <Button variant="ghost" size="icon" onClick={async () => {
        try {
          if (navigator.share) await navigator.share({ url, title: "Bayn — verified trade" });
          else { await navigator.clipboard?.writeText(url); toast.success("Link copied"); }
        } catch { /* user cancelled */ }
      }}>
        <Share2 className="size-4" />
      </Button>
    </div>
  );
}
