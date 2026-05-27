import { createFileRoute } from "@tanstack/react-router";
import { Card } from "@/components/ui/card";

export const Route = createFileRoute("/studio/docs")({
  head: () => ({ meta: [{ title: "Docs — Bayn Studio" }] }),
  component: Docs,
});

const SECTIONS = [
  {
    title: "Getting Started",
    body: `The Studio is a node-based environment for building your own trading strategies. Open the Builder, drop a Price node, wire it through indicators and logic, end at a Signal node, and you have a runnable strategy. Click "Run Backtest" to test against historical data. Click "Deploy Live" to start receiving live signals from your strategy — private to you.`,
  },
  {
    title: "Node Reference",
    body: `Five categories: Data (Price, Volume, Order Book, Options Chain, Fundamentals, Economic Calendar), Indicators (SMA, EMA, VWAP, RSI, MACD, Bollinger, ATR, Stochastic, Custom Formula), Logic (Comparator, Crossover, AND/OR/NOT, Time Window, Cooldown), Risk (Position Size, Stop Loss, Take Profit, Max Daily Loss, Max Concurrent), and Signal (Entry, Exit, Alert). Handles are typed — invalid connections are rejected by the validator.`,
  },
  {
    title: "Backtest Methodology",
    body: `Backtests run against tick-aggregated minute bars. Commission and slippage are modeled per-trade in basis points by default. Look-ahead bias is prevented by computing every indicator at bar close before any signal is allowed to fire. Equity is marked-to-market intraday for drawdown calculation. Returns are after fees.`,
  },
  {
    title: "Submission Criteria",
    body: `To submit a strategy to Bayn's catalog: (1) pass a full backtest with Sharpe ≥ 1.0, (2) pass an out-of-sample test on data not used during development, (3) run live forward test for at least 30 days, (4) provide a plain-English description of the edge. Bayn reviewers may reject strategies that look like data-mining artifacts.`,
  },
  {
    title: "Revenue Share Terms",
    body: `Strategies accepted into Bayn's catalog earn 30% of subscription revenue attributable to the strategy. Attribution uses subscriber-weighted hours-of-signal-active in the calendar month. Payouts on the 1st of each month for the prior month. Strategies become Bayn-branded products — your individual handle is not shown on trader-facing surfaces.`,
  },
];

function Docs() {
  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Developer documentation</h1>
        <p className="text-sm text-muted-foreground">Everything you need to build strategies in Bayn Studio.</p>
      </div>
      {SECTIONS.map((s) => (
        <Card key={s.title} className="border-border bg-elevated p-6">
          <h2 className="mb-2 text-lg font-semibold">{s.title}</h2>
          <p className="text-sm leading-relaxed text-muted-foreground">{s.body}</p>
        </Card>
      ))}
    </div>
  );
}
