import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import ReactMarkdown from "react-markdown";
import { Send, Sparkles, ArrowRightLeft, Wallet, Activity, TrendingUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { chatTraderAI, chatStudioAI, type ChatMsg, type AgentMode, type GraphContext, type TweakResult } from "@/lib/api/agent";

const TRADER_CHIPS = [
  "What's my biggest risk exposure right now?",
  "Which subscribed strategy is underperforming its backtest?",
  "Break down my win rate by asset class.",
  "Why did my last three signals hit their stop?",
  "Build a bull and bear case for my open BTC position.",
];

const STUDIO_CHIPS = [
  "Buy SPY when RSI drops below 30 and sell when it crosses back above 50.",
  "Mean reversion on BTC hourly — enter when price is 2 ATR below the 20 EMA, stop at 3 ATR, target the EMA.",
  "Opening range breakout on ES futures with a 1% trailing stop.",
  "Sell far-OTM SPY weekly calls when IV rank is above 50.",
];

const STUDIO_TWEAK_CHIPS = [
  "Change stop to 4 ATR",
  "Set RSI period to 9",
  "Switch timeframe to 15m",
  "Increase risk per trade to 2%",
];

interface Props {
  mode: AgentMode;
  onGraph?: (g: NonNullable<ChatMsg["meta"]>["graph"]) => void;
  onTweak?: (t: TweakResult) => void;
  /** Compact panel mode (used inside the builder). */
  compact?: boolean;
  initialPrompt?: string;
  /** When provided, the studio AI receives this graph context and tries to tweak instead of rebuild. */
  getCurrentGraph?: () => GraphContext | null;
}

export function AgentChat({ mode, onGraph, onTweak, compact, initialPrompt, getCurrentGraph }: Props) {
  const navigate = useNavigate();
  const [input, setInput] = useState(initialPrompt ?? "");
  const [msgs, setMsgs] = useState<ChatMsg[]>([
    {
      id: "seed",
      role: "assistant",
      content:
        mode === "trader"
          ? "I'm your analysis assistant. I can read your taken signals, open positions, and performance — ask me anything about them."
          : "I'm your build assistant. Describe a strategy in plain English and I'll wire it on the canvas. Once a graph is on the canvas, ask me to tweak it (e.g. \"change stop to 4 ATR\") and I'll patch it without rebuilding.",
    },
  ]);
  const [busy, setBusy] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" }); }, [msgs]);

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setInput("");
    setMsgs((m) => [...m, { id: `u-${Date.now()}`, role: "user", content: trimmed }]);
    setBusy(true);
    const ctx = mode === "studio" ? getCurrentGraph?.() ?? undefined : undefined;
    const reply = mode === "trader" ? await chatTraderAI(trimmed) : await chatStudioAI(trimmed, ctx);
    setMsgs((m) => [...m, reply]);
    setBusy(false);
    if (reply.meta?.kind === "graph" && reply.meta.graph) onGraph?.(reply.meta.graph);
    if (reply.meta?.kind === "tweak" && reply.meta.tweak) onTweak?.(reply.meta.tweak);
  };

  const hasGraph = mode === "studio" && (getCurrentGraph?.()?.nodes.length ?? 0) > 0;

  const accent = mode === "studio" ? "violet" : "cyan";

  return (
    <div className={cn("flex h-full min-h-0 flex-col", compact ? "" : "rounded-2xl border border-border bg-elevated")}>
      <header className={cn(
        "flex items-center gap-2 border-b border-border px-4 py-2.5",
        mode === "studio" ? "bg-violet/5" : "bg-cyan/5",
      )}>
        <Sparkles className={cn("size-4", mode === "studio" ? "text-violet" : "text-cyan")} />
        <div className="text-sm font-medium">
          {mode === "studio" ? "Build Mode" : "Analysis Mode"}
        </div>
        <span className={cn(
          "ml-2 rounded-full border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider",
          mode === "studio" ? "border-violet/30 text-violet" : "border-cyan/30 text-cyan",
        )}>
          {mode === "studio" ? "Constructs strategies · no execution" : "Reviews trades · no execution"}
        </span>
      </header>

      <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {msgs.map((m) => (
          <div key={m.id} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <div className={cn(
              "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
              m.role === "user"
                ? mode === "studio" ? "bg-violet text-violet-foreground" : "bg-cyan text-cyan-foreground"
                : "border border-border bg-background",
            )}>
              <div className="prose prose-sm prose-invert max-w-none prose-p:my-1 prose-table:my-2 prose-headings:mt-2 prose-headings:mb-1 prose-li:my-0">
                <ReactMarkdown>{m.content}</ReactMarkdown>
              </div>
              {m.meta?.kind === "switch-mode" && (
                <Button size="sm" variant="outline" className="mt-2"
                  onClick={() => navigate({ to: mode === "trader" ? "/studio/builder/$id" : "/app/agent", params: mode === "trader" ? { id: "new" } : undefined as never })}>
                  <ArrowRightLeft className="mr-1 size-3" />
                  {mode === "trader" ? "Open Builder" : "Switch to Trader"}
                </Button>
              )}
              {m.meta?.kind === "handoff" && (
                <div className="mt-2 rounded-md border border-border bg-muted/30 px-2 py-1.5 text-[11px] text-muted-foreground">
                  Bayn never places trades. Your connected agent can route this with your confirmation.
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-1.5 px-2 text-xs text-muted-foreground">
            <span className="size-1.5 animate-pulse rounded-full bg-current" />
            <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:120ms]" />
            <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:240ms]" />
          </div>
        )}
      </div>

      <div className="border-t border-border px-3 pb-3 pt-2">
        <div className="mb-2 flex flex-wrap gap-1.5">
          {(mode === "trader" ? TRADER_CHIPS : hasGraph ? STUDIO_TWEAK_CHIPS : STUDIO_CHIPS).map((c) => (
            <button key={c} onClick={() => send(c)} disabled={busy}
              className={cn(
                "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
                mode === "studio"
                  ? "border-violet/30 text-violet/90 hover:bg-violet/10"
                  : "border-cyan/30 text-cyan/90 hover:bg-cyan/10",
              )}>
              {c}
            </button>
          ))}
        </div>
        <div className="flex items-end gap-2">
          <Textarea
            value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder={mode === "studio" ? "Describe your strategy…" : "Ask about your trades, risk, performance…"}
            rows={2}
            className="min-h-[44px] resize-none bg-background"
          />
          <Button onClick={() => send(input)} disabled={busy || !input.trim()}
            className={mode === "studio" ? "bg-violet text-violet-foreground hover:bg-violet/90" : "bg-cyan text-cyan-foreground hover:bg-cyan/90"}>
            <Send className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Right-side context panel showing what the trader AI is grounded on. */
/** Right-side context panel showing what the trader AI is grounded on.
 *  Empty by default — populates from real broker / signal data once connected. */
export function TraderContextPanel() {
  return (
    <div className="space-y-3">
      <Card className="border-border bg-elevated p-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-mono uppercase tracking-wider text-muted-foreground">
          <Wallet className="size-3.5 text-cyan" /> Open Positions
        </div>
        <p className="text-xs text-muted-foreground">
          Connect a broker to surface live positions here.
        </p>
      </Card>
      <Card className="border-border bg-elevated p-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-mono uppercase tracking-wider text-muted-foreground">
          <Activity className="size-3.5 text-cyan" /> Recent Signals
        </div>
        <p className="text-xs text-muted-foreground">
          No signals yet — follow a strategy to start a track record.
        </p>
      </Card>
      <Card className="border-border bg-elevated p-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-mono uppercase tracking-wider text-muted-foreground">
          <TrendingUp className="size-3.5 text-cyan" /> Performance
        </div>
        <p className="text-xs text-muted-foreground">
          Performance metrics appear once you have taken signals.
        </p>
      </Card>
    </div>
  );
}

