// The pipeline stepper — the single visual readout of where a strategy is.
// Driven entirely by CopilotState so it stays in lock-step with the chat.
import { Check, Loader2, Lock } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  COPILOT_STAGES,
  STAGE_LABEL,
  STAGE_BLURB,
  isWorking,
  type CopilotState,
} from "@/lib/api/copilot";

function fmt(n: number | null, suffix = "", digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${n.toFixed(digits)}${suffix}`;
}

export function PipelineStepper({ state }: { state: CopilotState | null }) {
  const currentIndex = state?.stage_index ?? 0;
  const working = isWorking(state);

  return (
    <div className="space-y-4">
      {/* Stage rail */}
      <div className="flex items-center">
        {COPILOT_STAGES.map((stage, i) => {
          const done = i < currentIndex;
          const active = i === currentIndex;
          const last = i === COPILOT_STAGES.length - 1;
          return (
            <div key={stage} className="flex flex-1 items-center last:flex-none">
              <div className="flex flex-col items-center gap-1.5">
                <div
                  className={cn(
                    "grid size-8 place-items-center rounded-full border-2 text-[11px] font-bold transition-colors",
                    done && "border-violet bg-violet text-violet-foreground",
                    active && "border-violet bg-violet/15 text-violet",
                    !done && !active && "border-border bg-elevated text-muted-foreground",
                  )}
                  title={STAGE_BLURB[stage]}
                >
                  {done ? (
                    <Check className="size-4" />
                  ) : active && working ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    i + 1
                  )}
                </div>
                <span
                  className={cn(
                    "whitespace-nowrap text-[10px] font-medium tracking-tight",
                    active ? "text-violet" : done ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  {STAGE_LABEL[stage]}
                </span>
              </div>
              {!last && (
                <div
                  className={cn(
                    "mx-1 h-0.5 flex-1 rounded-full",
                    i < currentIndex ? "bg-violet" : "bg-border",
                  )}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* At-a-glance metrics for the current strategy */}
      {state && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric label="Trades" value={state.trade_count !== null ? String(state.trade_count) : "—"} />
          <Metric
            label="Sharpe"
            value={fmt(state.sharpe)}
            tone={state.sharpe !== null ? (state.sharpe >= 1 ? "ok" : state.sharpe < 0 ? "danger" : "warn") : undefined}
          />
          <Metric
            label="Return"
            value={fmt(state.total_return_pct, "%")}
            tone={state.total_return_pct !== null ? (state.total_return_pct > 0 ? "ok" : "danger") : undefined}
          />
          <Metric label="OOS Sharpe" value={fmt(state.avg_test_sharpe)} />
        </div>
      )}

      {/* Gates — what's been cleared, what's blocking */}
      {state && (
        <div className="flex flex-wrap gap-1.5">
          <Gate ok={state.gates_passed.backtest_completed} label="Backtested" />
          <Gate ok={state.gates_passed.enough_trades} label="≥30 trades" />
          <Gate ok={state.gates_passed.profitable_backtest} label="Profitable" />
          <Gate ok={state.gates_passed.oos_passed} label="OOS passed" />
          <Gate ok={state.gates_passed.forward_started} label="Forward" />
          <Gate ok={state.gates_passed.deployed_live} label="Live" />
        </div>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "danger";
}) {
  return (
    <div className="rounded-lg border border-border bg-elevated px-3 py-2">
      <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-0.5 text-sm font-semibold tabular-nums",
          tone === "ok" && "text-ok",
          tone === "warn" && "text-warn",
          tone === "danger" && "text-danger",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function Gate({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        ok
          ? "border-ok/30 bg-ok/10 text-ok"
          : "border-border bg-muted/40 text-muted-foreground",
      )}
    >
      {ok ? <Check className="size-3" /> : <Lock className="size-2.5" />}
      {label}
    </span>
  );
}
