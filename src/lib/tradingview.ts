import type { AssetClass } from "@/lib/types";

/** Map an internal Bayn symbol to TradingView's exchange-prefixed format.
 *  Explicit list first; sensible per-asset-class fallbacks after. */
export function tvSymbol(symbol: string, assetClass?: AssetClass | "index"): string {
  if (!symbol) return "NASDAQ:AAPL";
  if (symbol.includes(":")) return symbol.toUpperCase();
  const s = symbol.toUpperCase().replace(/-USD$|-USDT$/, "");

  const explicit: Record<string, string> = {
    SPY: "AMEX:SPY", QQQ: "NASDAQ:QQQ", IWM: "AMEX:IWM",
    AAPL: "NASDAQ:AAPL", MSFT: "NASDAQ:MSFT", NVDA: "NASDAQ:NVDA",
    AMZN: "NASDAQ:AMZN", META: "NASDAQ:META", GOOGL: "NASDAQ:GOOGL",
    TSLA: "NASDAQ:TSLA",
    VIX: "TVC:VIX", DXY: "TVC:DXY", GOLD: "TVC:GOLD",
    BTC: "BINANCE:BTCUSDT", "BTC-PERP": "BINANCE:BTCUSDT.P",
    ETH: "BINANCE:ETHUSDT", "ETH-PERP": "BINANCE:ETHUSDT.P",
    SOL: "BINANCE:SOLUSDT",
    ES: "CME_MINI:ES1!", NQ: "CME_MINI:NQ1!",
    CL: "NYMEX:CL1!", GC: "COMEX:GC1!", SI: "COMEX:SI1!",
  };
  if (explicit[s]) return explicit[s];
  if (assetClass === "crypto") return `BINANCE:${s.replace(/PERP$|USDT$/, "")}USDT`;
  if (assetClass === "futures") return `CME_MINI:${s}1!`;
  return `NASDAQ:${s}`;
}

/** Default ticker-tape symbols used when the user's watchlist is empty. */
export const DEFAULT_TICKER_TAPE: Array<{ proName: string; title: string }> = [
  { proName: "NASDAQ:AAPL", title: "AAPL" },
  { proName: "NASDAQ:NVDA", title: "NVDA" },
  { proName: "AMEX:SPY",    title: "SPY"  },
  { proName: "NASDAQ:QQQ",  title: "QQQ"  },
  { proName: "BINANCE:BTCUSDT", title: "BTC" },
  { proName: "BINANCE:ETHUSDT", title: "ETH" },
  { proName: "BINANCE:SOLUSDT", title: "SOL" },
  { proName: "CME_MINI:ES1!", title: "ES"  },
  { proName: "CME_MINI:NQ1!", title: "NQ"  },
  { proName: "NYMEX:CL1!",    title: "CL"  },
  { proName: "TVC:VIX",       title: "VIX" },
];
