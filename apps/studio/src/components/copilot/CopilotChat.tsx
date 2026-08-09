// The copilot chat. One box that builds, backtests, validates, and forward-tests
// a strategy by talking to POST /copilot/chat. It owns the conversation history
// and bubbles up the latest pipeline state + strategy id to the page.
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Send, Sparkles, Loader2, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  sendCopilotChat,
  actionToMessage,
  type CopilotChatResponse,
  type CopilotMessage,
  type CopilotToolCall,
} from "@/lib/api/copilot";

interface DisplayMsg {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools?: CopilotToolCall[];
}

const STARTER_CHIPS = [
  "Buy SPY when RSI drops below 30, exit above 50, risk 2% per trade.",
  "Mean reversion on BTC hourly — enter 2 ATR below the 20 EMA, target the EMA.",
  "Sell far-OTM SPY weekly calls when IV rank is above 50.",
];

const TOOL_VERB: Record<string, string> = {
  get_strategy_state: "checked status",
  build_strategy: "built the strategy",
  edit_strategy_node: "edited the graph",
  run_backtest: "ran a backtest",
  get_backtest_analysis: "read the results",
  run_oos_test: "ran the out-of-sample test",
  start_forward_test: "started a forward test",
  promote_strategy: "promoted to deployable",
  deploy_strategy: "deployed",
  submit_to_bayn: "submitted to the desk",
};

interface Props {
  strategyId: string | null;
  /** Suggested next action from the latest state, shown as a one-tap chip. */
  suggestedAction?: { action: string; label: string } | null;
  /** Fires after every assistant turn with the full response (state + tools). */
  onResult: (res: CopilotChatResponse) => void;
}

let _idSeq = 0;
const nextId = () => `m${++_idSeq}`;

export function CopilotChat({ strategyId, suggestedAction, onResult }: Props) {
  const [msgs, setMsgs] = useState<DisplayMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sidRef = useRef<string | null>(strategyId);

  useEffect(() => {
    sidRef.current = strategyId;
  }, [strategyId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs, busy]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setError(null);
    setInput("");

    const userMsg: DisplayMsg = { id: nextId(), role: "user", content: trimmed };
    const history: CopilotMessage[] = [
      ...msgs.map((m) => ({ role: m.role, content: m.content })),
      { role: "user", content: trimmed },
    ];
    setMsgs((prev) => [...prev, userMsg]);
    setBusy(true);

    try {
      const res = await sendCopilotChat(history, sidRef.current);
      setMsgs((prev) => [
        ...prev,
        {
          id: nextId(),
          role: "assistant",
          content: res.reply || (res.error ? `⚠️ ${res.error}` : "(no reply)"),
          tools: res.tool_trace?.length ? res.tool_trace : undefined,
        },
      ]);
      if (res.strategy_id) sidRef.current = res.strategy_id;
      onResult(res);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Something went wrong.";
      setError(msg);
      setMsgs((prev) => [
        ...prev,
        { id: nextId(), role: "assistant", content: `⚠️ ${msg}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  const empty = msgs.length === 0;

  return (
    <div className="flex h-full flex-col">
      {/* Transcript */}
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-1 py-2">
        {empty && (
          <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
            <div className="grid size-12 place-items-center rounded-2xl bg-violet/15 text-violet">
              <Sparkles className="size-6" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight">Describe a strategy</h2>
              <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                I'll build it, backtest it, validate it out of sample, and forward-test it —
                guiding you one step at a time. Tell me your idea in plain English.
              </p>
            </div>
            <div className="flex max-w-md flex-col gap-2">
              {STARTER_CHIPS.map((c) => (
                <button
                  key={c}
                  onClick={() => send(c)}
                  className="rounded-xl border border-border bg-elevated px-3 py-2 text-left text-[13px] text-muted-foreground transition-colors hover:border-violet/40 hover:text-foreground"
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
        )}

        {msgs.map((m) => (
          <div key={m.id} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <div
              className={cn(
                "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-[13.5px] leading-relaxed",
                m.role === "user"
                  ? "bg-violet text-violet-foreground"
                  : "border border-border bg-elevated text-foreground",
              )}
            >
              {m.tools && (
                <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                  <Wrench className="size-3" />
                  {m.tools.map((t, i) => (
                    <span key={i} className="rounded bg-muted/60 px-1.5 py-0.5">
                      {TOOL_VERB[t.name] ?? t.name}
                    </span>
                  ))}
                </div>
              )}
              {m.role === "assistant" ? (
                <div className="prose prose-sm prose-invert max-w-none prose-p:my-1.5 prose-headings:my-2 prose-strong:text-foreground prose-li:my-0.5">
                  <ReactMarkdown>{m.content}</ReactMarkdown>
                </div>
              ) : (
                m.content
              )}
            </div>
          </div>
        ))}

        {busy && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-2xl border border-border bg-elevated px-3.5 py-2.5 text-[13px] text-muted-foreground">
              <Loader2 className="size-4 animate-spin text-violet" />
              Working…
            </div>
          </div>
        )}
      </div>

      {/* Suggested next action */}
      {!empty && suggestedAction && suggestedAction.action !== "none" && actionToMessage(suggestedAction.action) && (
        <div className="px-1 pb-2">
          <button
            disabled={busy}
            onClick={() => send(actionToMessage(suggestedAction.action)!)}
            className="inline-flex items-center gap-1.5 rounded-full border border-violet/40 bg-violet/10 px-3 py-1.5 text-[12px] font-medium text-violet transition-colors hover:bg-violet/20 disabled:opacity-50"
          >
            <Sparkles className="size-3.5" />
            {suggestedAction.label}
          </button>
        </div>
      )}

      {error && <div className="px-1 pb-1 text-[11px] text-danger">{error}</div>}

      {/* Composer */}
      <div className="flex items-end gap-2 border-t border-border pt-3">
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
          placeholder="Describe a strategy, or ask what's next…"
          rows={1}
          className="max-h-32 min-h-[44px] flex-1 resize-none border-border bg-elevated"
          disabled={busy}
        />
        <Button
          onClick={() => send(input)}
          disabled={busy || !input.trim()}
          className="h-11 shrink-0 bg-violet text-violet-foreground hover:bg-violet/90"
        >
          <Send className="size-4" />
        </Button>
      </div>
    </div>
  );
}
