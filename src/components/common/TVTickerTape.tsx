import { useMemo } from "react";
import { useWatchlist } from "@/lib/user-prefs";
import { tvSymbol, DEFAULT_TICKER_TAPE } from "@/lib/tradingview";
import { TVEmbedWidget } from "./TVEmbedWidget";

/** TradingView Ticker Tape — sits at the top of every /app/* page.
 *  Reads from the user's watchlist; falls back to a curated default set. */
export function TVTickerTape() {
  const [watchlist] = useWatchlist();

  const symbols = useMemo(() => {
    if (!watchlist.length) return DEFAULT_TICKER_TAPE;
    return watchlist.map((s) => ({ proName: tvSymbol(s), title: s.toUpperCase() }));
  }, [watchlist]);

  const config = {
    symbols,
    showSymbolLogo: true,
    isTransparent: true,
    displayMode: "adaptive",
    colorTheme: "dark",
    locale: "en",
  };

  return (
    <div className="border-y border-border bg-elevated/60">
      <TVEmbedWidget
        scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js"
        config={config}
        height={46}
        lazy={false}
      />
    </div>
  );
}
