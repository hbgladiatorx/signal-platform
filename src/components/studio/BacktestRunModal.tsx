import { useState } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, PlayCircle } from "lucide-react";

export function BacktestRunModal({
  open, onOpenChange, onRun,
}: {
  open: boolean;
  onOpenChange: (b: boolean) => void;
  onRun: (params: { startDate: string; endDate: string; capital: number; commissionBps: number; slippageBps: number; commissionModel: string }) => Promise<unknown>;
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

  const handleRun = async () => {
    setRunning(true);
    try { await onRun(params); onOpenChange(false); }
    finally { setRunning(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><PlayCircle className="size-5 text-violet" /> Run Backtest</DialogTitle>
          <DialogDescription>Configure the simulation parameters and run a backtest against historical data.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3 py-2">
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
          <Button onClick={handleRun} disabled={running} className="bg-violet text-violet-foreground hover:bg-violet/90">
            {running ? <><Loader2 className="mr-2 size-4 animate-spin" /> Running…</> : "Run backtest"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
