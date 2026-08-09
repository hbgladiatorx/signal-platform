import { Progress } from "@/components/ui/progress";
import { formatLimit } from "@/lib/api/billing";

export function UsageMeter({
  label, current, limit, period, accent = "cyan",
}: {
  label: string;
  current: number;
  limit: number;
  period?: string;
  accent?: "cyan" | "violet" | "emerald";
}) {
  const accentColor =
    accent === "violet" ? "var(--violet)" :
    accent === "emerald" ? "var(--emerald-glow)" : "var(--cyan)";
  const unlimited = limit === -1;
  const pct = unlimited ? 8 : Math.min(100, Math.round((current / Math.max(1, limit)) * 100));
  const warn = !unlimited && pct >= 80;

  return (
    <div className="rounded-xl border border-border bg-elevated p-4">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="text-sm font-medium" style={{ color: warn ? "var(--warn)" : accentColor }}>
          {current} <span className="text-muted-foreground">/ {formatLimit(limit)}</span>
        </div>
      </div>
      <Progress
        value={pct}
        className="h-1.5"
        style={{ background: "color-mix(in oklab, var(--border) 80%, transparent)" }}
      />
      {period && <div className="mt-1.5 text-[10px] text-muted-foreground">{period}</div>}
    </div>
  );
}
