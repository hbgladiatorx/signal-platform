import { useEffect, useId, useRef } from "react";
import type { AssetClass } from "@/lib/types";

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

/** Map our internal symbols + asset classes to TradingView exchange-qualified symbols. */
export function toTradingViewSymbol(symbol: string, assetClass?: AssetClass | "index"): string {
  const s = symbol.toUpperCase();
  // Explicit, hand-tuned mappings for our mock universe.
  const explicit: Record<string, string> = {
    SPY: "AMEX:SPY",
    QQQ: "NASDAQ:QQQ",
    IWM: "AMEX:IWM",
    AAPL: "NASDAQ:AAPL",
    MSFT: "NASDAQ:MSFT",
    NVDA: "NASDAQ:NVDA",
    AMZN: "NASDAQ:AMZN",
    META: "NASDAQ:META",
    GOOGL: "NASDAQ:GOOGL",
    TSLA: "NASDAQ:TSLA",
    VIX: "TVC:VIX",
    BTC: "BINANCE:BTCUSDT",
    "BTC-PERP": "BINANCE:BTCUSDT.P",
    ETH: "BINANCE:ETHUSDT",
    "ETH-PERP": "BINANCE:ETHUSDT.P",
    SOL: "BINANCE:SOLUSDT",
    ES: "CME_MINI:ES1!",
    NQ: "CME_MINI:NQ1!",
    CL: "NYMEX:CL1!",
    GC: "COMEX:GC1!",
  };
  if (explicit[s]) return explicit[s];
  // Crypto fallback: pair against USDT on Binance.
  if (assetClass === "crypto") return `BINANCE:${s.replace(/-?PERP$|-USDT$|USDT$/, "")}USDT`;
  // Futures fallback: front-month continuous.
  if (assetClass === "futures") return `CME_MINI:${s}1!`;
  // Stocks/options default to NASDAQ; users can change in-chart.
  return `NASDAQ:${s}`;
}

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

  useEffect(() => {
    let cancelled = false;
    loadTradingView()
      .then(() => {
        if (cancelled || !ref.current || !window.TradingView) return;
        // Clear previous widget DOM before re-instantiation.
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
          // Hint to TradingView to use our font in the UI chrome where supported.
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
  }, [containerId, tvSymbol, interval, style, withDrawingTools, studies.join("|")]);

  return (
    <div
      id={containerId}
      ref={ref}
      className="tv-chart w-full overflow-hidden rounded-md"
      style={{ height: typeof height === "number" ? `${height}px` : height }}
    />
  );
}
