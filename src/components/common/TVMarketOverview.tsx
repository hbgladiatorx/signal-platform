import { TVEmbedWidget } from "./TVEmbedWidget";

/** TradingView Market Overview widget — multi-tab cards on /app/home. */
export function TVMarketOverview({ height = 460 }: { height?: number }) {
  const config = {
    colorTheme: "dark",
    dateRange: "12M",
    showChart: true,
    locale: "en",
    largeChartUrl: "",
    isTransparent: true,
    showSymbolLogo: true,
    showFloatingTooltip: true,
    width: "100%",
    height: "100%",
    plotLineColorGrowing: "rgba(34, 211, 238, 1)",
    plotLineColorFalling: "rgba(244, 63, 94, 1)",
    gridLineColor: "rgba(255, 255, 255, 0.06)",
    scaleFontColor: "rgba(148, 163, 184, 1)",
    belowLineFillColorGrowing: "rgba(34, 211, 238, 0.12)",
    belowLineFillColorFalling: "rgba(244, 63, 94, 0.12)",
    belowLineFillColorGrowingBottom: "rgba(34, 211, 238, 0)",
    belowLineFillColorFallingBottom: "rgba(244, 63, 94, 0)",
    symbolActiveColor: "rgba(34, 211, 238, 0.12)",
    tabs: [
      {
        title: "Stocks",
        symbols: [
          { s: "AMEX:SPY", d: "S&P 500" },
          { s: "NASDAQ:QQQ", d: "Nasdaq 100" },
          { s: "NASDAQ:AAPL", d: "Apple" },
          { s: "NASDAQ:NVDA", d: "NVIDIA" },
          { s: "NASDAQ:MSFT", d: "Microsoft" },
        ],
        originalTitle: "Stocks",
      },
      {
        title: "Crypto",
        symbols: [
          { s: "BINANCE:BTCUSDT", d: "Bitcoin" },
          { s: "BINANCE:ETHUSDT", d: "Ethereum" },
          { s: "BINANCE:SOLUSDT", d: "Solana" },
        ],
        originalTitle: "Crypto",
      },
      {
        title: "Futures",
        symbols: [
          { s: "CME_MINI:ES1!", d: "E-mini S&P" },
          { s: "CME_MINI:NQ1!", d: "E-mini Nasdaq" },
          { s: "NYMEX:CL1!", d: "Crude Oil" },
          { s: "COMEX:GC1!", d: "Gold" },
        ],
        originalTitle: "Futures",
      },
      {
        title: "Volatility",
        symbols: [{ s: "TVC:VIX", d: "VIX" }],
        originalTitle: "Volatility",
      },
    ],
  };

  return (
    <TVEmbedWidget
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-market-overview.js"
      config={config}
      height={height}
    />
  );
}
