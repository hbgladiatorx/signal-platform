import { createFileRoute, useParams, notFound, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getSignalById, getStrategyById } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { AssetClassBadge } from "@/components/common/AssetClassBadge";
import { DirectionPill } from "@/components/common/DirectionPill";
import { StatusPill } from "@/components/common/StatusPill";
import { Disclaimer } from "@/components/common/Disclaimer";
import { TradingViewChart } from "@/components/common/TradingViewChart";
import { DraggableLevelsOverlay } from "@/components/common/DraggableLevelsOverlay";
import { cn } from "@/lib/utils";
import { format } from "date-fns";
import { toast } from "sonner";
import { Share2, Bitcoin } from "lucide-react";

const TIMEFRAMES = [
  { key: "1", label: "1m" },
  { key: "5", label: "5m" },
  { key: "15", label: "15m" },
  { key: "60", label: "1h" },
  { key: "D", label: "1D" },
  { key: "W", label: "1W" },
];

export const Route = createFileRoute("/app/signal/$id")({
  head: ({ params }) => ({ meta: [{ title: `Signal ${params.id} — Bayn` }] }),
  component: SignalDetail,
});

function SignalDetail() {
  const { id } = useParams({ from: "/app/signal/$id" });
  const sig = useQuery({ queryKey: ["signal", id], queryFn: () => getSignalById(id) });
  const strat = useQuery({ queryKey: ["sig-strat", sig.data?.strategyId], queryFn: () => getStrategyById(sig.data!.strategyId), enabled: !!sig.data });
  const [accountSize] = useState(25000);
  const [showBroker, setShowBroker] = useState(false);
  const [showTaken, setShowTaken] = useState(false);
  const [fillPrice, setFillPrice] = useState<string>("");
  const [interval, setIntervalKey] = useState<string>("60");

  if (sig.isFetched && !sig.data) throw notFound();
  const s = sig.data;
  if (!s) return <div className="p-6 text-muted-foreground">Loading…</div>;

  const riskPerShare = Math.abs(s.entry - s.stop);
  const dollarsRisked = accountSize * 0.01;
  const positionSize = Math.floor(dollarsRisked / Math.max(0.0001, riskPerShare));

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <AssetClassBadge assetClass={s.assetClass} hideIcon />
            <Link to="/app/strategy/$id" params={{ id: s.strategyId }} className="hover:text-cyan">{s.strategyName}</Link>
            <span>·</span>
            <span>{format(new Date(s.firedAt), "PP p")}</span>
          </div>
          <h1 className="font-mono text-3xl tracking-tight">{s.symbol}</h1>
        </div>
        <div className="flex items-center gap-2">
          <DirectionPill direction={s.direction} />
          <StatusPill status={s.status} />
          <Button asChild variant="outline" size="sm">
            <Link to="/app/share/$cardId" params={{ cardId: s.id }}>
              <Share2 className="mr-1.5 size-3.5" /> Share trade
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Chart */}
        <Card className="border-border bg-elevated p-3 lg:col-span-2">
          <div className="relative">
            <TradingViewChart
              symbol={s.symbol}
              assetClass={s.assetClass}
              interval="60"
              height={420}
              withDrawingTools
            />
            <SignalPlanOverlay entry={s.entry} stop={s.stop} target={s.target} direction={s.direction} />
          </div>
          <Card className="mt-3 border-border bg-background/40 p-4">
            <h3 className="mb-1 text-sm font-semibold">Strategy reasoning</h3>
            <p className="text-sm text-muted-foreground">{s.reasoning}</p>
          </Card>
        </Card>


        {/* Order ticket */}
        <Card className="space-y-4 border-border bg-elevated p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Order ticket</h3>
          <div className="space-y-2 text-sm">
            <Row label="Symbol" value={<span className="font-mono">{s.symbol}</span>} />
            <Row label="Direction" value={<DirectionPill direction={s.direction} />} />
            <Row label="Entry"  value={<span className="font-mono">{s.entry}</span>} />
            <Row label="Stop"   value={<span className="font-mono text-danger">{s.stop}</span>} />
            <Row label="Target" value={<span className="font-mono text-futures">{s.target}</span>} />
            {s.strike != null && <Row label="Strike" value={<span className="font-mono">{s.strike}</span>} />}
            {s.expiry && <Row label="Expiry" value={<span className="font-mono text-xs">{format(new Date(s.expiry), "PP")}</span>} />}
            {s.delta != null && <Row label="Delta" value={<span className="font-mono">{s.delta.toFixed(2)}</span>} />}
            {s.iv != null && <Row label="IV" value={<span className="font-mono">{(s.iv * 100).toFixed(1)}%</span>} />}
            {s.contractMonth && <Row label="Contract" value={s.contractMonth} />}
            <div className="border-t border-border pt-3">
              <Row label="Account risk" value={`$${(accountSize * 0.01).toFixed(0)} (1%)`} />
              <Row label="Suggested size" value={<span className="font-mono text-cyan">{positionSize.toLocaleString()} {s.assetClass === "options" ? "contracts" : "units"}</span>} />
            </div>
          </div>

          {s.assetClass === "crypto" && (
            <Button onClick={() => setShowBroker(true)} className="w-full bg-cyan text-cyan-foreground hover:bg-cyan/90">
              <Bitcoin className="mr-2 size-4" /> Send to Coinbase
            </Button>
          )}
          <Button onClick={() => setShowTaken(true)} variant="outline" className="w-full">Mark as taken manually</Button>
        </Card>
      </div>

      <Disclaimer variant="banner" />

      <Dialog open={showBroker} onOpenChange={setShowBroker}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm order on Coinbase</DialogTitle>
            <DialogDescription>
              Bayn will send a pre-filled {s.direction} order for <span className="font-mono">{positionSize}</span> {s.symbol} at <span className="font-mono">{s.entry}</span>.
              You must confirm the order on your Coinbase account. Bayn never executes automatically.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowBroker(false)}>Cancel</Button>
            <Button onClick={() => { setShowBroker(false); toast("Order sent to Coinbase (mock)"); }} className="bg-cyan text-cyan-foreground hover:bg-cyan/90">Confirm</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showTaken} onOpenChange={setShowTaken}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Log this fill</DialogTitle>
            <DialogDescription>Recording your fill keeps your performance honest.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label>Fill price</Label>
            <Input value={fillPrice} onChange={(e) => setFillPrice(e.target.value)} placeholder={String(s.entry)} className="bg-background font-mono" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowTaken(false)}>Cancel</Button>
            <Button onClick={() => { setShowTaken(false); toast("Marked as taken"); }} className="bg-cyan text-cyan-foreground hover:bg-cyan/90">Log fill</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span>{value}</span>
    </div>
  );
}

/** Compact strategy plan card overlaid on the live chart. Uses % offsets from
 *  entry so the levels stay readable next to real TradingView prices. */
function SignalPlanOverlay({
  entry, stop, target, direction,
}: { entry: number; stop: number; target: number; direction: "LONG" | "SHORT" }) {
  const targetPct = ((target - entry) / entry) * 100;
  const stopPct = ((stop - entry) / entry) * 100;
  const rr = Math.abs(targetPct / stopPct);
  const sign = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
  const fmtP = (n: number) =>
    n >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 0 })
              : n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return (
    <div className="pointer-events-none absolute right-3 top-3 z-10 w-[200px] rounded-lg border border-border/80 bg-background/85 p-2.5 font-mono text-[10px] backdrop-blur-md shadow-lg">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="tracking-[0.18em] text-muted-foreground">STRATEGY PLAN</span>
        <span className={direction === "LONG" ? "text-cyan" : "text-danger"}>{direction}</span>
      </div>
      <PlanRow label="Target" pct={sign(targetPct)} price={fmtP(target)} tone="cyan" />
      <PlanRow label="Entry"  pct="—"               price={fmtP(entry)}  tone="gold" />
      <PlanRow label="Stop"   pct={sign(stopPct)}   price={fmtP(stop)}   tone="danger" />
      <div className="mt-1.5 flex items-center justify-between border-t border-border/60 pt-1.5 text-muted-foreground">
        <span>R:R</span>
        <span className="text-foreground">{isFinite(rr) ? rr.toFixed(2) : "—"}</span>
      </div>
      <div className="mt-1 text-[9px] leading-tight text-muted-foreground">
        % shown vs entry · live price may differ
      </div>
    </div>
  );
}

function PlanRow({ label, pct, price, tone }: { label: string; pct: string; price: string; tone: "cyan" | "gold" | "danger" }) {
  const cls = tone === "cyan" ? "text-cyan" : tone === "gold" ? "text-gold" : "text-danger";
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className={cls}>{label}</span>
      <span className="flex items-baseline gap-2">
        <span className={cls}>{pct}</span>
        <span className="text-muted-foreground">{price}</span>
      </span>
    </div>
  );
}

