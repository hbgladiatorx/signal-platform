import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import {
  ArrowRightLeft, Plus, Loader2, ChevronDown, Trash2,
  CheckCircle2, AlertTriangle, TrendingDown, Info, Wrench, ArrowRight,
} from "lucide-react";
import { toast } from "sonner";
import { formatDistanceToNow } from "date-fns";
import {
  listWalkforwards, getWalkforward, createWalkforward, deleteWalkforward,
  type WalkforwardSummary, type CreateWalkforwardInput,
  type WalkforwardAnalysis, type WalkforwardFinding, type ValidationVerdict,
} from "@/lib/api/walkforward";
import { getDevStrategies } from "@/lib/api/studio";
import { QueryState } from "@/components/common/QueryState";

// Referee verdict vocabulary → label + colour. One language across stages.
const VERDICT_META: Record<ValidationVerdict, { label: string; cls: string; ring: string }> = {
  DEPLOY:           { label: "Edge holds out-of-sample", cls: "text-success",          ring: "border-success/40 bg-success/10" },
  HOLD_CONDITIONAL: { label: "Holds — with caveats",     cls: "text-amber-400",        ring: "border-amber-400/40 bg-amber-400/10" },
  REJECT:           { label: "Fails out-of-sample",      cls: "text-danger",           ring: "border-danger/40 bg-danger/10" },
  UNVERIFIABLE:     { label: "Couldn't be verified",     cls: "text-muted-foreground", ring: "border-border bg-muted/20" },
};

const SEV_META: Record<WalkforwardFinding["severity"], { icon: typeof Info; cls: string; chip: string }> = {
  good: { icon: CheckCircle2,  cls: "text-success",          chip: "border-success/30 bg-success/5" },
  warn: { icon: AlertTriangle, cls: "text-amber-400",        chip: "border-amber-400/30 bg-amber-400/5" },
  bad:  { icon: TrendingDown,  cls: "text-danger",           chip: "border-danger/30 bg-danger/5" },
  info: { icon: Info,          cls: "text-muted-foreground", chip: "border-border bg-muted/10" },
};

// Map the verdict's semantic route key to a real studio route. The path-back is
// a live button, never a dead string.
const NEXT_ROUTE: Record<string, string> = {
  "studio.strategies": "/studio/strategies",
  "studio.live": "/studio/live",
};

function ValidationVerdictPanel({ analysis }: { analysis: WalkforwardAnalysis }) {
  const navigate = useNavigate();
  const meta = VERDICT_META[analysis.verdict] ?? VERDICT_META.UNVERIFIABLE;
  const na = analysis.next_action;
  const route = NEXT_ROUTE[na?.target] ?? "/studio/strategies";
  return (
    <div className={cn("mb-3 rounded-lg border p-3", meta.ring)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide", meta.ring, meta.cls)}>
            {analysis.verdict.replace("_", " ")}
          </span>
          <span className={cn("text-sm font-semibold", meta.cls)}>{meta.label}</span>
        </div>
        {na?.label && (
          <Button
            size="sm"
            className="gap-1.5"
            onClick={() => navigate({ to: route })}
          >
            {na.label} <ArrowRight className="size-4" />
          </Button>
        )}
      </div>
      <p className="mt-2 text-sm text-foreground/90">{analysis.headline}</p>
      <p className="mt-1 text-sm text-muted-foreground">{analysis.narrative}</p>
      {analysis.findings.length > 0 && (
        <div className="mt-3 space-y-1.5">
          <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            What to fix
          </div>
          {analysis.findings.map((f) => {
            const sm = SEV_META[f.severity] ?? SEV_META.info;
            const Icon = sm.icon;
            return (
              <div key={f.id} className={cn("rounded-md border p-2.5", sm.chip)}>
                <div className="flex items-start gap-2">
                  <Icon className={cn("mt-0.5 size-4 shrink-0", sm.cls)} />
                  <div className="min-w-0 flex-1">
                    <div className={cn("text-sm font-medium", sm.cls)}>{f.title}</div>
                    <p className="mt-0.5 text-sm text-muted-foreground">{f.detail}</p>
                    {f.suggestion && (
                      <div className="mt-1.5 flex items-start gap-1.5 text-xs text-foreground/80">
                        <Wrench className="mt-0.5 size-3 shrink-0 text-violet" />
                        <span>{f.suggestion}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export const Route = createFileRoute("/studio/walkforward")({
  head: () => ({ meta: [{ title: "Walk-forward — Bayn Studio" }] }),
  component: WalkforwardPage,
});

const f2 = (n: number | null | undefined) => (n == null ? "—" : n.toFixed(2));
const pct = (n: number | null | undefined) => (n == null ? "—" : `${n.toFixed(1)}%`);

function WalkforwardPage() {
  const wfQuery = useQuery({ queryKey: ["walkforwards"], queryFn: listWalkforwards });
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <ArrowRightLeft className="size-6 text-violet" /> Walk-forward
          </h1>
          <p className="text-sm text-muted-foreground">
            Rolling train/test parameter sweeps. Out-of-sample (test) performance per window is
            the honest measure of whether an edge survives — and the train-vs-test gap reveals overfitting.
          </p>
        </div>
        <NewWalkforwardDialog />
      </div>

      <QueryState
        query={wfQuery}
        emptyHeadline="No walk-forward analyses yet"
        emptyBody="Create one to validate a strategy out-of-sample."
      >
        {(list) => (
          <div className="space-y-2">
            {list.map((w) => (
              <WalkforwardRow key={w.id} w={w} expanded={open === w.id} onToggle={() => setOpen(open === w.id ? null : w.id)} />
            ))}
          </div>
        )}
      </QueryState>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  const cls =
    status === "completed" ? "border-success/30 bg-success/10 text-success"
    : status === "failed" ? "border-danger/30 bg-danger/10 text-danger"
    : status === "running" ? "border-violet/30 bg-violet/10 text-violet"
    : "border-border bg-muted/20 text-muted-foreground";
  return <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-medium", cls)}>{status}</span>;
}

function WalkforwardRow({ w, expanded, onToggle }: { w: WalkforwardSummary; expanded: boolean; onToggle: () => void }) {
  const qc = useQueryClient();
  // Two-step inline confirm — a walk-forward run can't be recovered.
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: () => deleteWalkforward(w.id),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["walkforwards"] });
      toast.success("Walk-forward deleted");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Couldn't delete that walk-forward"),
    onSettled: () => setConfirming(false),
  });

  return (
    <Card className="border-border bg-elevated">
      <div className="flex items-center gap-1 pr-3">
      <button className="flex w-full items-center gap-3 p-3 text-left" onClick={onToggle}>
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-180")} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium">{w.strategy_name}</span>
            <StatusChip status={w.status} />
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {w.symbols.join(", ")} · {w.bar_resolution} · {w.num_windows} windows · {formatDistanceToNow(new Date(w.created_at), { addSuffix: true })}
          </div>
        </div>
        <div className="hidden gap-4 font-mono text-[11px] sm:flex">
          <span className="text-muted-foreground">test Sharpe <span className="text-foreground">{f2(w.avg_test_sharpe)}</span></span>
          <span className="text-muted-foreground">test ret <span className="text-foreground">{pct(w.avg_test_return_pct)}</span></span>
          <span className="text-muted-foreground">win windows <span className="text-foreground">{pct(w.win_rate_windows_pct)}</span></span>
        </div>
      </button>
        {confirming ? (
          <div className="flex shrink-0 items-center gap-1">
            <Button size="sm" variant="ghost" className="text-danger hover:text-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {remove.isPending ? "Deleting…" : "Confirm"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
          </div>
        ) : (
          <Button size="sm" variant="ghost" className="shrink-0" title="Delete this walk-forward" onClick={() => setConfirming(true)}>
            <Trash2 className="size-3.5" />
          </Button>
        )}
      </div>
      {expanded && <WalkforwardDetailPanel id={w.id} status={w.status} />}
    </Card>
  );
}

function WalkforwardDetailPanel({ id, status }: { id: string; status: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["walkforward", id],
    queryFn: () => getWalkforward(id),
    refetchInterval: status === "running" || status === "pending" ? 4000 : false,
  });
  if (isLoading) return <div className="border-t border-border p-3 text-sm text-muted-foreground">Loading windows…</div>;
  if (!data) return null;
  if (data.error_message) {
    return <div className="border-t border-border p-3 text-sm text-danger">Failed: {data.error_message}</div>;
  }
  const windows = data.windows_result ?? [];
  if (windows.length === 0) {
    return (
      <div className="border-t border-border p-3">
        {/* Even with no window table (e.g. UNVERIFIABLE), still speak a verdict. */}
        {data.analysis && <ValidationVerdictPanel analysis={data.analysis} />}
        {!data.analysis && (
          <div className="text-sm text-muted-foreground">No window results yet (status: {data.status}).</div>
        )}
      </div>
    );
  }
  return (
    <div className="border-t border-border p-3">
      {/* Verdict first — the plain call + narrative + what-to-fix + path back. */}
      {data.analysis && <ValidationVerdictPanel analysis={data.analysis} />}
      <div className="mb-2 flex flex-wrap gap-4 font-mono text-[11px] text-muted-foreground">
        <span>train Sharpe <span className="text-foreground">{f2(data.avg_train_sharpe)}</span></span>
        <span>test Sharpe <span className="text-foreground">{f2(data.avg_test_sharpe)}</span></span>
        <span>overfit drop <span className={cn((data.overfit_drop ?? 0) > 0.5 ? "text-danger" : "text-foreground")}>{f2(data.overfit_drop)}</span></span>
        <span>combos/window <span className="text-foreground">{data.total_combos ?? "—"}</span></span>
      </div>
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/20 text-[10px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="p-2 text-left">#</th>
              <th className="p-2 text-left">Test window</th>
              <th className="p-2 text-right">Train Sharpe</th>
              <th className="p-2 text-right">Test Sharpe</th>
              <th className="p-2 text-right">Test ret</th>
              <th className="p-2 text-left">Best params</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {windows.map((win) => (
              <tr key={win.window_index}>
                <td className="p-2 font-mono text-xs">{win.window_index}</td>
                <td className="p-2 font-mono text-xs text-muted-foreground">{win.test_start_ts.slice(0, 10)} → {win.test_end_ts.slice(0, 10)}</td>
                <td className="p-2 text-right font-mono text-xs">{f2(win.train_sharpe)}</td>
                <td className={cn("p-2 text-right font-mono text-xs", (win.test_sharpe ?? 0) > 0 ? "text-cyan" : "text-danger")}>{f2(win.test_sharpe)}</td>
                <td className={cn("p-2 text-right font-mono text-xs", (win.test_total_return_pct ?? 0) >= 0 ? "text-cyan" : "text-danger")}>{pct(win.test_total_return_pct)}</td>
                <td className="p-2 font-mono text-[10px] text-muted-foreground">{Object.entries(win.best_params).map(([k, v]) => `${k}=${v}`).join(" ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function NewWalkforwardDialog() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const { data: strategies } = useQuery({ queryKey: ["devStrategies"], queryFn: getDevStrategies });
  const [strategyName, setStrategyName] = useState("");
  const [symbols, setSymbols] = useState("BTC-USD@BINANCEUS");
  const [resolution, setResolution] = useState<CreateWalkforwardInput["bar_resolution"]>("1h");
  const [grid, setGrid] = useState('{\n  "fast_period": [10, 20],\n  "slow_period": [30, 50]\n}');
  const [trainBars, setTrainBars] = useState(500);
  const [testBars, setTestBars] = useState(150);
  const [numWindows, setNumWindows] = useState(5);

  const create = useMutation({
    mutationFn: (body: CreateWalkforwardInput) => createWalkforward(body),
    onSuccess: () => {
      toast.success("Walk-forward queued");
      qc.invalidateQueries({ queryKey: ["walkforwards"] });
      setOpen(false);
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Couldn't create walk-forward"),
  });

  function submit() {
    let param_grid: Record<string, unknown[]>;
    try {
      param_grid = JSON.parse(grid);
      if (typeof param_grid !== "object" || Array.isArray(param_grid)) throw new Error();
    } catch {
      toast.error("Param grid must be valid JSON: {\"param\": [v1, v2], …}");
      return;
    }
    const name = strategyName || strategies?.[0]?.name;
    if (!name) { toast.error("Pick a strategy"); return; }
    create.mutate({
      strategy_name: name,
      symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
      bar_resolution: resolution,
      param_grid,
      train_bars: trainBars,
      test_bars: testBars,
      num_windows: numWindows,
    });
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="gap-1.5 bg-violet text-violet-foreground hover:bg-violet/90"><Plus className="size-4" /> New walk-forward</Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>New walk-forward analysis</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-xs">Strategy</Label>
            <Select value={strategyName || strategies?.[0]?.name} onValueChange={setStrategyName}>
              <SelectTrigger className="bg-background"><SelectValue placeholder="Pick a strategy" /></SelectTrigger>
              <SelectContent>
                {(strategies ?? []).map((s) => <SelectItem key={s.id} value={s.name}>{s.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Symbols (comma-separated canonical)</Label>
            <Input className="bg-background" value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="SPY@ALPACA, AAPL@ALPACA" />
          </div>
          <div className="grid grid-cols-4 gap-2">
            <div className="col-span-1">
              <Label className="text-xs">Resolution</Label>
              <Select value={resolution} onValueChange={(v) => setResolution(v as CreateWalkforwardInput["bar_resolution"])}>
                <SelectTrigger className="bg-background"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(["1m", "5m", "15m", "1h", "4h", "1d"] as const).map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <Field label="Train bars" value={trainBars} onChange={setTrainBars} />
            <Field label="Test bars" value={testBars} onChange={setTestBars} />
            <Field label="Windows" value={numWindows} onChange={setNumWindows} />
          </div>
          <div>
            <Label className="text-xs">Param grid (JSON)</Label>
            <Textarea className="bg-background font-mono text-xs" rows={5} value={grid} onChange={(e) => setGrid(e.target.value)} />
            <p className="mt-1 text-[11px] text-muted-foreground">Each combo of values is swept; the best per train window is tested out-of-sample.</p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={submit} disabled={create.isPending} className="gap-1.5 bg-violet text-violet-foreground hover:bg-violet/90">
            {create.isPending && <Loader2 className="size-4 animate-spin" />} Run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, value, onChange }: { label: string; value: number; onChange: (n: number) => void }) {
  return (
    <div className="col-span-1">
      <Label className="text-xs">{label}</Label>
      <Input type="number" className="bg-background" value={value} onChange={(e) => onChange(Number(e.target.value) || 0)} />
    </div>
  );
}
