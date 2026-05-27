import { cn } from "@/lib/utils";
import type { AssetClass } from "@/lib/types";
import { Briefcase, Bitcoin, LineChart, Activity } from "lucide-react";

const map: Record<AssetClass, { label: string; cls: string; Icon: typeof Briefcase }> = {
  stocks:  { label: "Stocks",  cls: "bg-stocks/15 text-stocks border-stocks/30",   Icon: Briefcase },
  crypto:  { label: "Crypto",  cls: "bg-crypto/15 text-crypto border-crypto/30",   Icon: Bitcoin },
  options: { label: "Options", cls: "bg-options/15 text-options border-options/30", Icon: LineChart },
  futures: { label: "Futures", cls: "bg-futures/15 text-futures border-futures/30", Icon: Activity },
};

export function AssetClassBadge({ assetClass, className, hideIcon }: { assetClass: AssetClass; className?: string; hideIcon?: boolean }) {
  const c = map[assetClass];
  if (!c) return null;
  const Icon = c.Icon;
  return (
    <span className={cn(
      "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide",
      c.cls, className,
    )}>
      {!hideIcon && <Icon className="size-3" />}
      {c.label}
    </span>
  );
}
