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
  open, onOpenChange, onRun, assetClass,
}: {
  open: boolean;
  onOpenChange: (b: boolean) => void;
  assetClass: AssetClass;
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

  const [mode, setMode] = useState<"select" | "universe">("select");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");

  const { data: instruments, isLoading, error } = useQuery({
    queryKey: ["instruments", assetClass],
    queryFn: () => getInstrumentsForAsset(assetClass),
    enabled: open,
  });

  const symbols = useMemo(() => (instruments ?? []).map((i) => i.symbol), [instruments]);

  // When the universe loads (or asset class changes), seed a default pick.
  useEffect(() => {
    setSelected((prev) => {
      if (prev.size) return prev;
      const d = defaultSymbol(assetClass, symbols);
      return d ? new Set([d]) : prev;
    });
  }, [symbols, assetClass]);

  // Reset selection when the asset class changes.
  useEffect(() => {
    setSelected(new Set());
    setSearch("");
    setMode("select");
  }, [assetClass]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return symbols;
    return symbols.filter((s) => s.toLowerCase().includes(q));
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
          <RadioGroup value={mode} onValueChange={(v) => setMode(v as "select" | "universe")} className="flex gap-6">
            <div className="flex items-center gap-2">
              <RadioGroupItem value="select" id="m-select" />
              <Label htmlFor="m-select" className="cursor-pointer">Pick symbols</Label>
            </div>
            <div className="flex items-center gap-2">
              <RadioGroupItem value="universe" id="m-universe" />
              <Label htmlFor="m-universe" className="flex cursor-pointer items-center gap-1">
                <Globe className="size-3.5" /> Full {assetClass} universe
              </Label>
            </div>
          </RadioGroup>

          {error ? (
            <p className="text-sm text-destructive">Couldn't load instruments. {(error as Error).message}</p>
          ) : isLoading ? (
            <p className="text-sm text-muted-foreground">Loading {assetClass} instruments…</p>
          ) : symbols.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No active {assetClass} instruments. Connect a market-data source for this asset class first.
            </p>
          ) : mode === "universe" ? (
            <p className="text-sm text-muted-foreground">
              Testing across <span className="font-medium text-foreground">all {symbols.length}</span> active{" "}
              {assetClass} instruments. This can take a while.
            </p>
          ) : (
            <div className="space-y-2">
              <div className="relative">
                <Search className="absolute left-2 top-2.5 size-3.5 text-muted-foreground" />
                <Input
                  className="h-9 bg-background pl-7"
                  placeholder={`Search ${symbols.length} ${assetClass} symbols…`}
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
                  {filtered.slice(0, 300).map((s) => (
                    <li key={s}>
                      <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-elevated">
                        <Checkbox checked={selected.has(s)} onCheckedChange={() => toggle(s)} />
                        <span className="font-mono text-xs">{s}</span>
                      </label>
                    </li>
                  ))}
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
