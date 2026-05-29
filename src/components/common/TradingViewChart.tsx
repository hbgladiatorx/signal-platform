import { useEffect, useId, useRef, useState } from "react";
import type { AssetClass } from "@/lib/types";
import { tvSymbol as mapTvSymbol } from "@/lib/tradingview";

declare global {
  interface Window {
    TradingView?: any;
  }
}

const TV_SCRIPT_SRC = "https://s3.tradingview.com/tv.js";

let scriptPromise: Promise<void> | null = null;
function loadTradingView(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (window.TradingView) return Promise.resolve();
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${TV_SCRIPT_SRC}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("TV script failed")));
      return;
    }
    const s = document.createElement("script");
    s.src = TV_SCRIPT_SRC;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("TV script failed"));
    document.head.appendChild(s);
  });
  return scriptPromise;
}

/** Back-compat re-export — symbol mapping now lives in src/lib/tradingview.ts. */
export const toTradingViewSymbol = mapTvSymbol;


export interface TradingViewChartProps {
  symbol: string;
  assetClass?: AssetClass | "index";
  /** TV interval: "1","5","15","60","D","W","M". Default "60". */
  interval?: string;
  /** Chart style: 1 = candles (default), 3 = area, 8 = heikin ashi, 9 = line. */
  style?: 1 | 3 | 8 | 9;
  height?: number | string;
  /** Show TradingView's drawing toolbar on the left. */
  withDrawingTools?: boolean;
  /** Indicator studies to preload. */
  studies?: string[];
}

/**
 * Embed-grade TradingView Advanced Chart widget. No API key required.
 * Renders inside a stable container id and recreates on prop change.
 */
export function TradingViewChart({
  symbol,
  assetClass,
  interval = "60",
  style = 1,
  height = 380,
  withDrawingTools = false,
  studies = ["Volume@tv-basicstudies"],
}: TradingViewChartProps) {
  const reactId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const containerId = `tv_${reactId}`;
  const ref = useRef<HTMLDivElement | null>(null);
  const tvSymbol = toTradingViewSymbol(symbol, assetClass);
  const [visible, setVisible] = useState(false);

  // Defer widget initialisation until the chart scrolls into view.
  useEffect(() => {
    if (visible || !ref.current) return;
    const el = ref.current;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [visible]);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    loadTradingView()
      .then(() => {
        if (cancelled || !ref.current || !window.TradingView) return;
        ref.current.innerHTML = "";
        // eslint-disable-next-line new-cap
        new window.TradingView.widget({
          autosize: true,
          container_id: containerId,
          symbol: tvSymbol,
          interval,
          timezone: "Etc/UTC",
          theme: "dark",
          style,
          locale: "en",
          toolbar_bg: "rgba(0,0,0,0)",
          enable_publishing: false,
          hide_top_toolbar: false,
          hide_legend: false,
          hide_side_toolbar: !withDrawingTools,
          allow_symbol_change: true,
          withdateranges: true,
          save_image: false,
          studies,
          backgroundColor: "rgba(0,0,0,0)",
          gridColor: "rgba(255,255,255,0.06)",
          custom_css_url: undefined,
        });
      })
      .catch(() => {
        if (ref.current) {
          ref.current.innerHTML =
            '<div style="display:grid;place-items:center;height:100%;color:var(--muted-foreground);font-size:12px;">TradingView chart unavailable</div>';
        }
      });
    return () => {
      cancelled = true;
      if (ref.current) ref.current.innerHTML = "";
    };
  }, [visible, containerId, tvSymbol, interval, style, withDrawingTools, studies.join("|")]);


  return (
    <div
      id={containerId}
      ref={ref}
      className="tv-chart w-full overflow-hidden rounded-md"
      style={{ height: typeof height === "number" ? `${height}px` : height }}
    />
  );
}
