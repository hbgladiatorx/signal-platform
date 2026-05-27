import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import type { AssetClass } from "@/lib/types";
import { toast } from "sonner";
import { CheckCircle2, Loader2, Plus, X } from "lucide-react";

export const Route = createFileRoute("/studio/builder/new")({
  head: () => ({ meta: [{ title: "New strategy — Bayn Studio" }] }),
  component: NewStrategyWizard,
});

type Stage = "build" | "backtest" | "oos" | "forward" | "submit";
type Rule = { indicator: string; comparator: string; value: string };

function NewStrategyWizard() {
  const [stage, setStage] = useState<Stage>("build");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [ac, setAc] = useState<AssetClass>("stocks");
  const [symbols, setSymbols] = useState("AAPL, NVDA, MSFT");
  const [entryRules, setEntryRules] = useState<Rule[]>([{ indicator: "RSI(2)", comparator: "<", value: "10" }]);
  const [exitRule, setExitRule] = useState({ stop: "2%", target: "4%", time: "5 days" });

  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<{ sharpe: number; winRate: number; maxDD: number; trades: number } | null>(null);
  const [oosPassed, setOosPassed] = useState(false);

  const runBacktest = () => {
    setRunning(true);
    setTimeout(() => {
      setResults({ sharpe: 1.32, winRate: 0.58, maxDD: 0.14, trades: 412 });
      setRunning(false);
      setStage("backtest");
      toast("Backtest complete");
    }, 2200);
  };
  const runOOS = () => {
    setRunning(true);
    setTimeout(() => { setOosPassed(true); setRunning(false); setStage("oos"); toast("Out-of-sample passed"); }, 1800);
  };

  const passes = results && results.sharpe > 1 && results.winRate > 0.5 && results.maxDD < 0.2;

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New strategy</h1>
        <p className="text-sm text-muted-foreground font-mono">// build → backtest → oos → forward → submit</p>
      </div>

      <Stepper stage={stage} />

      <Card className="space-y-4 border-border bg-elevated p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">1 · Basics</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5"><Label>Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Opening Range Breakout — ES" className="bg-background" /></div>
          <div className="space-y-1.5">
            <Label>Asset class</Label>
            <Select value={ac} onValueChange={(v) => setAc(v as AssetClass)}>
              <SelectTrigger className="bg-background"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="stocks">Stocks</SelectItem>
                <SelectItem value="crypto">Crypto</SelectItem>
                <SelectItem value="options">Options</SelectItem>
                <SelectItem value="futures">Futures</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="space-y-1.5"><Label>Description</Label><Textarea value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="In one sentence — what does this strategy trade and why?" className="bg-background" /></div>
        <div className="space-y-1.5"><Label>Symbols / markets</Label><Input value={symbols} onChange={(e) => setSymbols(e.target.value)} className="bg-background font-mono" /></div>
      </Card>

      <Card className="space-y-3 border-border bg-elevated p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">2 · Entry conditions</h2>
        {entryRules.map((r, i) => (
          <div key={i} className="grid grid-cols-12 gap-2">
            <Select value={r.indicator} onValueChange={(v) => setEntryRules((p) => p.map((x, j) => i === j ? { ...x, indicator: v } : x))}>
              <SelectTrigger className="col-span-5 bg-background font-mono"><SelectValue /></SelectTrigger>
              <SelectContent>
                {["RSI(2)", "RSI(14)", "Price", "SMA(50)", "SMA(200)", "VWAP", "ATR(14)", "Volume ratio"].map((x) => <SelectItem key={x} value={x}>{x}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={r.comparator} onValueChange={(v) => setEntryRules((p) => p.map((x, j) => i === j ? { ...x, comparator: v } : x))}>
              <SelectTrigger className="col-span-2 bg-background font-mono"><SelectValue /></SelectTrigger>
              <SelectContent>{["<", "<=", ">", ">=", "==", "crosses above", "crosses below"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
            </Select>
            <Input className="col-span-4 bg-background font-mono" value={r.value} onChange={(e) => setEntryRules((p) => p.map((x, j) => i === j ? { ...x, value: e.target.value } : x))} />
            <Button variant="ghost" size="icon" className="col-span-1" onClick={() => setEntryRules((p) => p.filter((_, j) => j !== i))}><X className="size-4" /></Button>
          </div>
        ))}
        <Button variant="outline" size="sm" onClick={() => setEntryRules((p) => [...p, { indicator: "Price", comparator: ">", value: "0" }])}><Plus className="mr-1 size-3.5" /> Add rule</Button>
      </Card>

      <Card className="space-y-3 border-border bg-elevated p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">3 · Exit</h2>
        <div className="grid grid-cols-3 gap-2">
          <div><Label className="text-xs">Stop</Label><Input value={exitRule.stop} onChange={(e) => setExitRule((p) => ({ ...p, stop: e.target.value }))} className="bg-background font-mono" /></div>
          <div><Label className="text-xs">Target</Label><Input value={exitRule.target} onChange={(e) => setExitRule((p) => ({ ...p, target: e.target.value }))} className="bg-background font-mono" /></div>
          <div><Label className="text-xs">Time stop</Label><Input value={exitRule.time} onChange={(e) => setExitRule((p) => ({ ...p, time: e.target.value }))} className="bg-background font-mono" /></div>
        </div>
      </Card>

      <Card className="space-y-3 border-border bg-elevated p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">4 · Validate</h2>
        {!results ? (
          <Button onClick={runBacktest} disabled={running} className="bg-cyan text-cyan-foreground hover:bg-cyan/90">
            {running ? <><Loader2 className="mr-2 size-4 animate-spin" /> Running backtest…</> : "Run backtest"}
          </Button>
        ) : (
          <>
            <div className="grid grid-cols-4 gap-3">
              <ResultStat label="Sharpe" value={results.sharpe.toFixed(2)} good={results.sharpe > 1} />
              <ResultStat label="Win rate" value={`${(results.winRate * 100).toFixed(0)}%`} good={results.winRate > 0.5} />
              <ResultStat label="Max DD" value={`${(results.maxDD * 100).toFixed(0)}%`} good={results.maxDD < 0.2} />
              <ResultStat label="Trades" value={String(results.trades)} good />
            </div>
            {passes && !oosPassed && (
              <Button onClick={runOOS} disabled={running} className="bg-gold text-gold-foreground hover:bg-gold/90">
                {running ? <><Loader2 className="mr-2 size-4 animate-spin" /> Running out-of-sample…</> : "Run out-of-sample"}
              </Button>
            )}
            {oosPassed && (
              <>
                <div className="flex items-center gap-2 text-sm text-gold"><CheckCircle2 className="size-4" /> Out-of-sample passed</div>
                <Button className="bg-cyan text-cyan-foreground hover:bg-cyan/90" onClick={() => { setStage("forward"); toast("Submitted to forward test"); }}>
                  Submit for forward test
                </Button>
                <Button variant="outline" onClick={() => { setStage("submit"); toast("Submitted for Bayn review"); }}>
                  Submit for Bayn review (after 30+ days)
                </Button>
              </>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

function Stepper({ stage }: { stage: Stage }) {
  const order: Stage[] = ["build", "backtest", "oos", "forward", "submit"];
  const idx = order.indexOf(stage);
  const labels = ["Build", "Backtest", "Out-of-Sample", "Forward", "Review"];
  return (
    <div className="space-y-2">
      <Progress value={((idx + 1) / order.length) * 100} />
      <div className="grid grid-cols-5 text-center text-[10px] uppercase tracking-wide text-muted-foreground">
        {labels.map((l, i) => (
          <span key={l} className={i <= idx ? "text-cyan" : ""}>{l}</span>
        ))}
      </div>
    </div>
  );
}

function ResultStat({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="rounded-md border border-border bg-background/40 p-3">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`font-mono text-lg ${good ? "text-cyan" : "text-danger"}`}>{value}</div>
    </div>
  );
}
