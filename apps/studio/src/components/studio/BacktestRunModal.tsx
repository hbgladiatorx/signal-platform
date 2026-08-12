import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, PlayCircle, Search, Check } from "lucide-react";
import { toast } from "sonner";
import { getInstrumentsForAsset } from "@/lib/api/studio";
import { cn } from "@/lib/utils";
import type { AssetClass } from "@/lib/types";

export interface RunParams {
  startDate: string;
  endDate: string;
  capital: number;
  commissionBps: number;
  slippageBps: number;
  commissionModel: string;
  symbols: string[];
}

// The plain, human ticker for a canonical symbol: drop the "@VENUE" suffix so
// "SPY@ALPACA" → "SPY" and "BTC-USDT@BINANCEUS" → "BTC-USDT". Users pick by this.
const tickerOf = (canonical: string) => canonical.split("@")[0];

// YYYY-MM-DD for `days` ago (browser-local). Used for the lookback presets.
const isoDaysAgo = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
};
const isoToday = () => new Date().toISOString().slice(0, 10);
// Quick backtest-period presets → how far back the in-sample window starts.
const PERIOD_PRESETS: Array<{ label: string; days: number }> = [
  { label: "1Y", days: 365 },
  { label: "2Y", days: 365 * 2 },
  { label: "3Y", days: 365 * 3 },
  { label: "5Y", days: 365 * 5 },
  { label: "Max", days: 365 * 10 },
];

// Sensible default pick per asset class (used when the universe loads).
function defaultSymbol(assetClass: AssetClass, symbols: string[]): string | undefined {
  if (!symbols.length) return undefined;
  const prefer =
    assetClass === "crypto"
      ? ["BTC-USDT@BINANCEUS", "BTC-USD@BINANCEUS", "ETH-USDT@BINANCEUS"]
      : assetClass === "stocks"
        ? ["SPY@ALPACA", "AAPL@ALPACA"]
        : [];
  return prefer.find((p) => symbols.includes(p)) ?? symbols[0];
}

export function BacktestRunModal({
  open, onOpenChange, onRun, assetClass, allowAssetSwitch = false,
}: {
  open: boolean;
  onOpenChange: (b: boolean) => void;
  assetClass: AssetClass;
  // When true, the user can switch the asset class inside the modal (used for
  // asset-agnostic built-in strategies run outside the builder).
  allowAssetSwitch?: boolean;
  onRun: (params: RunParams) => Promise<unknown>;
}) {
  const [running, setRunning] = useState(false);
  const [params, setParams] = useState({
    startDate: isoDaysAgo(365 * 2), // default: last 2 years, ending today
    endDate: isoToday(),
    capital: 25000,
    commissionBps: 5,
    slippageBps: 3,
    commissionModel: "per_share",
  });
  const applyPreset = (days: number) =>
    setParams((p) => ({ ...p, startDate: isoDaysAgo(days), endDate: isoToday() }));

  // The class the symbol list is drawn from. Defaults to the strategy's class;
  // editable when allowAssetSwitch.
  const [asset, setAsset] = useState<AssetClass>(assetClass);
  useEffect(() => { setAsset(assetClass); }, [assetClass, open]);

  // Strategies run on ONE symbol (their on_init refuses more than one — there is
  // no capital-allocation model across a universe yet). So this picker is
  // single-select; the old "Full universe" / multi-select options were removed
  // because choosing them produced a run that crashed. To get more trades, users
  // widen the date range or lower the timeframe instead.
  const [selected, setSelected] = useState<string | undefined>(undefined);
  const [search, setSearch] = useState("");

  const { data: instruments, isLoading, error } = useQuery({
    queryKey: ["instruments", asset],
    queryFn: () => getInstrumentsForAsset(asset),
    enabled: open,
  });

  const symbols = useMemo(() => (instruments ?? []).map((i) => i.symbol), [instruments]);
  // How many historical bars each symbol has — used to warn on no-data symbols
  // (backtesting one yields zero trades) and to pick a sensible default.
  const barsOf = useMemo(
    () => new Map((instruments ?? []).map((i) => [i.symbol, i.bars])),
    [instruments],
  );

  // When the instruments load (or asset class changes), seed a default pick —
  // restricted to symbols that actually have history, so the default run trades.
  useEffect(() => {
    setSelected((prev) => {
      if (prev) return prev;
      const tradeable = symbols.filter((s) => (barsOf.get(s) ?? 0) > 0);
      return defaultSymbol(asset, tradeable.length ? tradeable : symbols) ?? prev;
    });
  }, [symbols, asset, barsOf]);

  // Reset selection when the asset class changes.
  useEffect(() => {
    setSelected(undefined);
    setSearch("");
  }, [asset]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return symbols;
    // Match the plain ticker the user types ("amd", "spy", "btc") as well as the
    // full canonical id, so they never need the venue/pair suffix to find it.
    return symbols.filter(
      (s) => s.toLowerCase().includes(q) || tickerOf(s).toLowerCase().includes(q),
    );
  }, [symbols, search]);

  const chosen = selected ? [selected] : [];
  const canRun = chosen.length > 0 && !running && !isLoading;

  const handleRun = async () => {
    setRunning(true);
    try {
      await onRun({ ...params, symbols: chosen });
      onOpenChange(false);
    } catch (e) {
      // Surface the failure instead of silently doing nothing.
      toast.error(e instanceof Error ? e.message : "Backtest failed to start");
    } finally {
      setRunning(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><PlayCircle className="size-5 text-violet" /> Run Backtest</DialogTitle>
          <DialogDescription>Choose what to test on and configure the simulation, then run against historical data.</DialogDescription>
        </DialogHeader>

        {/* Asset selection */}
        <div className="space-y-3 rounded-md border border-border bg-elevated/50 p-3">
          {allowAssetSwitch && (
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground">Asset class</Label>
              <Select value={asset} onValueChange={(v) => setAsset(v as AssetClass)}>
                <SelectTrigger className="h-8 w-36 bg-background"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="crypto">Crypto</SelectItem>
                  <SelectItem value="stocks">Stocks</SelectItem>
                  <SelectItem value="options">Options</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="flex items-center justify-between">
            <Label className="text-xs font-medium">Symbol</Label>
            <span className="text-[11px] text-muted-foreground">
              Strategies run on one symbol — to get more trades, widen the date range or lower the timeframe.
            </span>
          </div>

          {error ? (
            <p className="text-sm text-destructive">Couldn't load instruments. {(error as Error).message}</p>
          ) : isLoading ? (
            <p className="text-sm text-muted-foreground">Loading {asset} instruments…</p>
          ) : symbols.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No active {asset} instruments. Connect a market-data source for this asset class first.
            </p>
          ) : (
            <div className="space-y-2">
              <div className="relative">
                <Search className="absolute left-2 top-2.5 size-3.5 text-muted-foreground" />
                <Input
                  className="h-9 bg-background pl-7"
                  placeholder={`Search by ticker — e.g. ${asset === "crypto" ? "BTC, ETH, SOL" : "SPY, AMD, AAPL"}…`}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <ScrollArea className="h-40 rounded-md border border-border">
                <ul className="p-1">
                  {filtered.slice(0, 300).map((s) => {
                    const bars = barsOf.get(s) ?? 0;
                    const isSel = selected === s;
                    return (
                      <li key={s}>
                        <button
                          type="button"
                          onClick={() => setSelected(s)}
                          className={cn(
                            "flex w-full cursor-pointer items-center gap-2 rounded px-2 py-1 text-left text-sm hover:bg-elevated",
                            isSel && "bg-violet/10",
                          )}
                        >
                          <Check className={cn("size-3.5 shrink-0", isSel ? "text-violet" : "text-transparent")} />
                          <span className="font-mono text-xs font-medium">{tickerOf(s)}</span>
                          <span className="font-mono text-[10px] text-muted-foreground">{s.split("@")[1] ?? ""}</span>
                          <span
                            className={cn(
                              "ml-auto font-mono text-[10px]",
                              bars > 0 ? "text-muted-foreground" : "text-amber-400",
                            )}
                            title={bars > 0 ? `${bars} daily bars of history` : "No historical data — backtests will have no trades"}
                          >
                            {bars > 0 ? `${bars.toLocaleString()} bars` : "no history"}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                  {filtered.length > 300 && (
                    <li className="px-2 py-1 text-xs text-muted-foreground">
                      +{filtered.length - 300} more — refine your search.
                    </li>
                  )}
                </ul>
              </ScrollArea>
            </div>
          )}
        </div>

        {/* Backtest period presets — quick "how far back" for the in-sample window. */}
        <div className="flex items-center gap-1.5 pt-1">
          <Label className="mr-1 text-xs text-muted-foreground">Period</Label>
          {PERIOD_PRESETS.map((p) => (
            <Button key={p.label} type="button" size="sm" variant="outline" className="h-7 px-2 text-xs"
              onClick={() => applyPreset(p.days)}>
              {p.label}
            </Button>
          ))}
        </div>

        {/* Simulation params */}
        <div className="grid grid-cols-2 gap-3 py-1">
          <div className="space-y-1.5"><Label>Start date</Label><Input type="date" value={params.startDate} onChange={(e) => setParams({ ...params, startDate: e.target.value })} /></div>
          <div className="space-y-1.5"><Label>End date</Label><Input type="date" value={params.endDate} onChange={(e) => setParams({ ...params, endDate: e.target.value })} /></div>
          <div className="space-y-1.5"><Label>Starting capital</Label><Input type="number" value={params.capital} onChange={(e) => setParams({ ...params, capital: Number(e.target.value) })} /></div>
          <div className="space-y-1.5">
            <Label>Commission model</Label>
            <Select value={params.commissionModel} onValueChange={(v) => setParams({ ...params, commissionModel: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="per_share">Per share</SelectItem>
                <SelectItem value="bps">Basis points</SelectItem>
                <SelectItem value="flat">Flat fee</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5"><Label>Commission (bps)</Label><Input type="number" value={params.commissionBps} onChange={(e) => setParams({ ...params, commissionBps: Number(e.target.value) })} /></div>
          <div className="space-y-1.5"><Label>Slippage (bps)</Label><Input type="number" value={params.slippageBps} onChange={(e) => setParams({ ...params, slippageBps: Number(e.target.value) })} /></div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={running}>Cancel</Button>
          <Button onClick={handleRun} disabled={!canRun} className="bg-violet text-violet-foreground hover:bg-violet/90">
            {running ? <><Loader2 className="mr-2 size-4 animate-spin" /> Running…</>
              : selected ? `Run on ${tickerOf(selected)}` : "Pick a symbol"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
