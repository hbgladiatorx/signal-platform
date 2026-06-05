import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, PlayCircle, Search, Globe } from "lucide-react";
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
    startDate: "2023-01-01",
    endDate: "2024-12-31",
    capital: 25000,
    commissionBps: 5,
    slippageBps: 3,
    commissionModel: "per_share",
  });

  // The class the symbol list is drawn from. Defaults to the strategy's class;
  // editable when allowAssetSwitch.
  const [asset, setAsset] = useState<AssetClass>(assetClass);
  useEffect(() => { setAsset(assetClass); }, [assetClass, open]);

  const [mode, setMode] = useState<"select" | "universe">("select");
  const [selected, setSelected] = useState<Set<string>>(new Set());
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

  // When the universe loads (or asset class changes), seed a default pick —
  // restricted to symbols that actually have history, so the default run trades.
  useEffect(() => {
    setSelected((prev) => {
      if (prev.size) return prev;
      const tradeable = symbols.filter((s) => (barsOf.get(s) ?? 0) > 0);
      const d = defaultSymbol(asset, tradeable.length ? tradeable : symbols);
      return d ? new Set([d]) : prev;
    });
  }, [symbols, asset, barsOf]);

  // Reset selection when the asset class changes.
  useEffect(() => {
    setSelected(new Set());
    setSearch("");
    setMode("select");
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

  const toggle = (sym: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      return next;
    });

  const chosen = mode === "universe" ? symbols : [...selected];
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
          <RadioGroup value={mode} onValueChange={(v) => setMode(v as "select" | "universe")} className="flex gap-6">
            <div className="flex items-center gap-2">
              <RadioGroupItem value="select" id="m-select" />
              <Label htmlFor="m-select" className="cursor-pointer">Pick symbols</Label>
            </div>
            <div className="flex items-center gap-2">
              <RadioGroupItem value="universe" id="m-universe" />
              <Label htmlFor="m-universe" className="flex cursor-pointer items-center gap-1">
                <Globe className="size-3.5" /> Full {asset} universe
              </Label>
            </div>
          </RadioGroup>

          {error ? (
            <p className="text-sm text-destructive">Couldn't load instruments. {(error as Error).message}</p>
          ) : isLoading ? (
            <p className="text-sm text-muted-foreground">Loading {asset} instruments…</p>
          ) : symbols.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No active {asset} instruments. Connect a market-data source for this asset class first.
            </p>
          ) : mode === "universe" ? (
            <p className="text-sm text-muted-foreground">
              Testing across <span className="font-medium text-foreground">all {symbols.length}</span> active{" "}
              {asset} instruments. This can take a while.
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
              {selected.size > 0 && (
                <div className="flex flex-wrap gap-1">
                  {[...selected].map((s) => (
                    <Badge key={s} variant="secondary" className="cursor-pointer" onClick={() => toggle(s)}>
                      {s.replace(/@.*$/, "")} ✕
                    </Badge>
                  ))}
                </div>
              )}
              <ScrollArea className="h-40 rounded-md border border-border">
                <ul className="p-1">
                  {filtered.slice(0, 300).map((s) => {
                    const bars = barsOf.get(s) ?? 0;
                    return (
                      <li key={s}>
                        <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-elevated">
                          <Checkbox checked={selected.has(s)} onCheckedChange={() => toggle(s)} />
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
                        </label>
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
              : `Run on ${chosen.length || 0} symbol${chosen.length === 1 ? "" : "s"}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
