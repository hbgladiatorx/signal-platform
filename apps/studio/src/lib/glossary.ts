/**
 * Plain-but-sharp definitions for the trading jargon that shows up across the
 * trader app. Keep each one to a sentence or two — they render inside tooltips.
 *
 * Add a key here, then reference it with <Term name="..."> or
 * <MetricLabel term="..."> so a term is only ever defined in one place.
 */
export type GlossaryEntry = {
  /** Default visible label if a <Term> doesn't supply its own children. */
  label: string;
  /** One- or two-sentence definition shown on hover/tap. */
  def: string;
};

export const GLOSSARY = {
  signal: {
    label: "Signal",
    def: "Entry, stop, and target from a strategy you follow. Fires on live market conditions — it's an alert, not an auto-trade.",
  },
  entry: {
    label: "Entry",
    def: "Price the strategy plans to open the trade at.",
  },
  stop: {
    label: "Stop",
    def: "Exit price that caps the loss if the trade goes against you.",
  },
  target: {
    label: "Target",
    def: "Exit price where the trade takes profit.",
  },
  sharpe: {
    label: "Sharpe",
    def: "Risk-adjusted return — how much return you earn per unit of volatility. Above 1 is solid, above 2 is excellent.",
  },
  maxDrawdown: {
    label: "Max drawdown",
    def: "The largest peak-to-trough drop in equity. How deep the worst losing stretch went, top to bottom.",
  },
  winRate: {
    label: "Win rate",
    def: "Share of closed signals that hit their target instead of their stop. High win rate doesn't guarantee profit — size matters too.",
  },
  rMultiple: {
    label: "R-multiple",
    def: "Profit or loss measured in units of risk. +2R means you made twice what you risked on that trade; -1R means you lost exactly what you risked.",
  },
  avgR: {
    label: "Avg R",
    def: "Average R-multiple across the signals you've taken — your edge per trade, normalized to risk. Positive over many trades is what matters.",
  },
  liveDays: {
    label: "Live days",
    def: "Days this strategy has run on live market data since it cleared verification. More live time = more trustworthy track record.",
  },
  edge: {
    label: "Edge",
    def: "A statistical advantage that held up out-of-sample and in forward testing — not just curve-fit to past data.",
  },
  direction: {
    label: "Direction",
    def: "LONG bets the price rises; SHORT bets it falls.",
  },
  statusOpen: {
    label: "Open",
    def: "Live — the trade is active and hasn't hit its stop or target yet.",
  },
  statusTarget: {
    label: "Target hit",
    def: "Closed in profit — price reached the target.",
  },
  statusStop: {
    label: "Stop hit",
    def: "Closed at a loss — price hit the stop.",
  },
  statusExpired: {
    label: "Expired",
    def: "Closed unfilled — the setup timed out before it ever triggered.",
  },
  fill: {
    label: "Fill",
    def: "The price you actually got in at, which can differ slightly from the entry due to slippage.",
  },
} satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof GLOSSARY;
