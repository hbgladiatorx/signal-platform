import { createFileRoute, useParams } from "@tanstack/react-router";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Disclaimer } from "@/components/common/Disclaimer";
import { useQuery } from "@tanstack/react-query";
import { getUserPerformance } from "@/lib/api";
import { Share2 } from "lucide-react";
import { toast } from "sonner";
import {
  Area, AreaChart, ResponsiveContainer,
} from "recharts";

export const Route = createFileRoute("/app/share/$cardId")({
  head: ({ params }) => ({ meta: [{ title: `Bayn share card ${params.cardId}` }] }),
  component: SharePage,
});

function SharePage() {
  const { cardId } = useParams({ from: "/share/$cardId" });
  const { data } = useQuery({ queryKey: ["share", cardId], queryFn: () => getUserPerformance(30) });

  const start = data?.equity[0]?.equity ?? 10000;
  const end = data?.equity[data.equity.length - 1]?.equity ?? 10000;
  const ret = (end - start) / start;

  return (
    <div className="grid min-h-screen place-items-center bg-background px-4 py-12">
      <Card className="w-full max-w-md overflow-hidden border-border bg-elevated">
        <div className="border-b border-border px-6 py-4">
          <div className="flex items-center gap-2 text-sm">
            <div className="grid size-6 place-items-center rounded bg-cyan/15 text-cyan font-bold text-[11px]">B</div>
            <span className="font-semibold">Bayn</span>
            <span className="text-xs text-muted-foreground">· verified track record</span>
          </div>
        </div>
        <div className="space-y-5 px-6 py-6">
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Last 30 days</div>
            <div className="mt-1 font-mono text-4xl text-cyan">
              {ret >= 0 ? "+" : ""}{(ret * 100).toFixed(2)}%
            </div>
          </div>
          <div className="h-28">
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
        <div className="border-t border-border px-6 py-3">
          <Button size="sm" variant="outline" className="w-full" onClick={() => { navigator.clipboard?.writeText(window.location.href); toast("Link copied"); }}>
            <Share2 className="mr-2 size-3.5" /> Copy share link
          </Button>
        </div>
      </Card>
    </div>
  );
}
