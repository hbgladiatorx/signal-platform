import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { AssetClass } from "./types";

export type AssetFilter = "all" | AssetClass;

interface Ctx {
  assetClass: AssetFilter;
  setAssetClass: (v: AssetFilter) => void;
}

const AssetFilterContext = createContext<Ctx | null>(null);

export function AssetFilterProvider({ children }: { children: ReactNode }) {
  const [assetClass, setAssetClass] = useState<AssetFilter>("all");
  const value = useMemo(() => ({ assetClass, setAssetClass }), [assetClass]);
  return <AssetFilterContext.Provider value={value}>{children}</AssetFilterContext.Provider>;
}

export function useAssetFilter() {
  const v = useContext(AssetFilterContext);
  if (!v) throw new Error("useAssetFilter must be used within AssetFilterProvider");
  return v;
}

export const ASSET_OPTIONS: Array<{ key: AssetFilter; label: string; dot: string }> = [
  { key: "all",     label: "All",     dot: "bg-foreground/60" },
  { key: "stocks",  label: "Stocks",  dot: "bg-stocks" },
  { key: "crypto",  label: "Crypto",  dot: "bg-crypto" },
  { key: "options", label: "Options", dot: "bg-options" },
  { key: "futures", label: "Futures", dot: "bg-futures" },
];
