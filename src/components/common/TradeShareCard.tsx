import { Card } from "@/components/ui/card";
import { AssetClassBadge } from "./AssetClassBadge";
import { DirectionPill } from "./DirectionPill";
import { Disclaimer } from "./Disclaimer";
import { TradingViewChart } from "./TradingViewChart";
import { format } from "date-fns";
import type { Signal } from "@/lib/types";

interface Props {
  signal: Signal;
  strategyName?: string;
  badge?: string; // e.g. "OPEN TRADE" / "CLOSED · WIN"
}

export function TradeShareCard({ signal: s, strategyName, badge }: Props) {
  const isWin = (s.pnlR ?? 0) > 0;
  const isClosed = s.status !== "OPEN";
  const accentClass = !isClosed ? "text-cyan" : isWin ? "text-futures" : "text-danger";
  const accentVar = !isClosed ? "var(--cyan)" : isWin ? "var(--futures)" : "var(--danger)";
  const computedBadge =
    badge ??
    (s.status === "OPEN"
      ? "OPEN TRADE"
      : s.status === "HIT_TARGET"
        ? "CLOSED · WIN"
        : s.status === "HIT_STOP"
          ? "CLOSED · STOP"
          : "CLOSED");

  const ret =
    s.pnlR != null
      ? `${s.pnlR >= 0 ? "+" : ""}${s.pnlR.toFixed(2)}R`
      : isClosed ? "—" : "LIVE";

  return (
    <Card
      className="relative w-full max-w-md overflow-hidden border-border bg-elevated"
      style={{
        backgroundImage:
          "radial-gradient(900px 240px at 100% -20%, color-mix(in oklab, var(--cyan) 14%, transparent), transparent 60%), radial-gradient(700px 220px at -10% 110%, color-mix(in oklab, var(--violet) 12%, transparent), transparent 60%)",
      }}
    >
      {/* header */}
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <div className="flex items-center gap-2">
          <div className="grid size-7 place-items-center rounded-md bg-cyan/15 font-bold text-cyan">B</div>
          <div className="leading-none">
            <div className="text-sm font-semibold tracking-tight">Bayn</div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">verified signal</div>
          </div>
        </div>
        <span
          className="rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider"
          style={{ borderColor: accentVar, color: accentVar }}
        >
          {computedBadge}
        </span>
      </div>

      {/* body */}
      <div className="space-y-4 px-5 py-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <AssetClassBadge assetClass={s.assetClass} hideIcon />
              <DirectionPill direction={s.direction} />
            </div>
            <div className="mt-1 font-mono text-3xl tracking-tight">{s.symbol}</div>
            {strategyName && (
              <div className="text-xs text-muted-foreground">{strategyName}</div>
            )}
          </div>
          <div className="text-right">
            <div className={`font-mono text-3xl leading-none ${accentClass}`}>{ret}</div>
            <div className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">
              {format(new Date(s.firedAt), "MMM d, yyyy")}
            </div>
          </div>
        </div>

        {/* chart */}
        <div className="h-24 rounded-lg border border-border bg-background/40 p-1">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={s.priceSeries}>
              <defs>
                <linearGradient id={`tcg-${s.id}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={accentVar} stopOpacity={0.4} />
                  <stop offset="100%" stopColor={accentVar} stopOpacity={0} />
                </linearGradient>
              </defs>
              <ReferenceLine y={s.entry}  stroke="var(--foreground)" strokeOpacity={0.4} strokeDasharray="2 3" />
              <ReferenceLine y={s.stop}   stroke="var(--danger)"  strokeOpacity={0.7} strokeDasharray="2 3" />
              <ReferenceLine y={s.target} stroke="var(--futures)" strokeOpacity={0.7} strokeDasharray="2 3" />
              <Area type="monotone" dataKey="price" stroke={accentVar} strokeWidth={1.6} fill={`url(#tcg-${s.id})`} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* levels */}
        <div className="grid grid-cols-3 gap-2 text-center">
          <Cell label="Entry"  value={s.entry}  tone="foreground" />
          <Cell label="Stop"   value={s.stop}   tone="danger" />
          <Cell label="Target" value={s.target} tone="futures" />
        </div>

        {/* asset-specific extras */}
        {(s.strike != null || s.contractMonth) && (
          <div className="grid grid-cols-3 gap-2 border-t border-border pt-3 text-center">
            {s.strike != null && <Cell label="Strike" value={s.strike} tone="foreground" />}
            {s.delta != null && <Cell label="Δ" value={s.delta.toFixed(2)} tone="foreground" />}
            {s.iv != null && <Cell label="IV" value={`${(s.iv * 100).toFixed(0)}%`} tone="foreground" />}
            {s.contractMonth && <Cell label="Contract" value={s.contractMonth} tone="foreground" />}
            {s.tickSize != null && <Cell label="Tick" value={s.tickSize} tone="foreground" />}
          </div>
        )}

        <Disclaimer variant="card" />
      </div>

      {/* footer — branding */}
      <div className="flex items-center justify-between border-t border-border bg-background/40 px-5 py-3">
        <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">Powered by</span>
        <span className="font-semibold tracking-tight">
          Bayn<span className="ml-1 text-cyan">·</span> bayn.app
        </span>
      </div>
    </Card>
  );
}

function Cell({ label, value, tone }: { label: string; value: React.ReactNode; tone: "foreground" | "danger" | "futures" }) {
  const cls = tone === "danger" ? "text-danger" : tone === "futures" ? "text-futures" : "text-foreground";
  return (
    <div className="rounded-md border border-border bg-background/40 px-2 py-2">
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`font-mono text-sm ${cls}`}>{value}</div>
    </div>
  );
}
