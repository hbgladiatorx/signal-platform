import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import {
  Sliders, Newspaper, Layers, Layout, Settings2, Bell,
  Plus, X, ArrowUp, ArrowDown, Trash2,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import {
  useWatchlist, useNewsCategories, ALL_NEWS_CATEGORIES,
  useNewsSources, useOnlyNewsForWatched, useEnabledAssetClasses, ALL_ASSET_CLASSES,
  useHomeLayout, useHiddenSections, DEFAULT_HOME_LAYOUT,
  useAccountSize, useRiskPerTrade, useDefaultTimeframe, useDefaultChartType,
  useNotifications, useFollowedOverlay, useLiveTrackingStrategy,
  type HomeSection,
} from "@/lib/user-prefs";
import { getEffectiveFollowedIds } from "@/lib/api";
import { toggleFollow } from "@/lib/user-prefs";
import { getCurrentPlan, getTotalSlots, isFreeStrategy, formatLimit } from "@/lib/api/billing";
import { strategies } from "@/lib/mockData";
import type { AssetClass } from "@/lib/types";

const TAB_DEFS = [
  { key: "markets", label: "Markets & Tickers", icon: Sliders },
  { key: "news", label: "News", icon: Newspaper },
  { key: "strategies", label: "Strategies", icon: Layers },
  { key: "layout", label: "Home Layout", icon: Layout },
  { key: "defaults", label: "Trading Defaults", icon: Settings2 },
  { key: "notifications", label: "Notifications", icon: Bell },
] as const;
type TabKey = typeof TAB_DEFS[number]["key"];

export const Route = createFileRoute("/app/customize")({
  validateSearch: (s: Record<string, unknown>) => ({
    tab: (typeof s.tab === "string" ? s.tab : "markets") as TabKey,
  }),
  head: () => ({ meta: [{ title: "Customize — Bayn" }] }),
  component: CustomizePage,
});

function CustomizePage() {
  const { tab } = Route.useSearch();
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Customize</h1>
        <p className="text-sm text-muted-foreground">
          Every populated surface in Bayn is yours to shape. Empty by default — populated by choice.
        </p>
      </header>

      <div className="flex flex-wrap gap-1.5">
        {TAB_DEFS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <Link
              key={t.key}
              to="/app/customize"
              search={{ tab: t.key }}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                active
                  ? "border-cyan/40 bg-cyan/15 text-cyan"
                  : "border-border bg-elevated text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="size-3.5" />
              {t.label}
            </Link>
          );
        })}
      </div>

      <div className="pt-2">
        {tab === "markets" && <MarketsTab />}
        {tab === "news" && <NewsTab />}
        {tab === "strategies" && <StrategiesTab />}
        {tab === "layout" && <LayoutTab />}
        {tab === "defaults" && <DefaultsTab />}
        {tab === "notifications" && <NotificationsTab />}
      </div>
    </div>
  );
}

function Section({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <Card className="space-y-4 border-border bg-elevated p-5">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-foreground">{title}</h2>
        {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
      </div>
      {children}
    </Card>
  );
}

/* ---------------- Markets & Tickers ---------------- */
function MarketsTab() {
  const [enabled, setEnabled] = useEnabledAssetClasses();
  const [watchlist, setWatchlist] = useWatchlist();
  const [adding, setAdding] = useState("");

  const toggleClass = (c: AssetClass) => {
    setEnabled(enabled.includes(c) ? enabled.filter((x) => x !== c) : [...enabled, c]);
  };

  const add = () => {
    const sym = adding.trim().toUpperCase();
    if (!sym || watchlist.includes(sym)) { setAdding(""); return; }
    setWatchlist([...watchlist, sym]);
    setAdding("");
  };
  const remove = (sym: string) => setWatchlist(watchlist.filter((s) => s !== sym));
  const move = (sym: string, dir: -1 | 1) => {
    const i = watchlist.indexOf(sym);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= watchlist.length) return;
    const next = [...watchlist];
    [next[i], next[j]] = [next[j], next[i]];
    setWatchlist(next);
  };

  return (
    <div className="space-y-4">
      <Section title="Asset classes" sub="Master toggles cascade everywhere — disabled classes vanish from filter chips, ticker tape, catalog, and signal feed.">
        <div className="flex flex-wrap gap-2">
          {ALL_ASSET_CLASSES.map((c) => {
            const on = enabled.includes(c);
            return (
              <button
                key={c}
                onClick={() => toggleClass(c)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium capitalize transition-colors",
                  on ? "border-cyan/40 bg-cyan/15 text-cyan" : "border-border bg-background/40 text-muted-foreground hover:text-foreground",
                )}
              >
                {c}
              </button>
            );
          })}
        </div>
      </Section>

      <Section title="Watched tickers" sub="Drives the top ticker tape and Market Overview cards on Home.">
        <div className="flex gap-2">
          <Input
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="Add a ticker (e.g. SPY, BTC-PERP, MES)"
            className="h-9 bg-background font-mono text-xs"
          />
          <Button size="sm" onClick={add}><Plus className="size-3.5" /> Add</Button>
        </div>
        {watchlist.length === 0 ? (
          <p className="rounded-md border border-dashed border-border bg-background/40 p-4 text-center text-xs text-muted-foreground">
            No tickers yet. Add a few to populate the ticker tape and market overview.
          </p>
        ) : (
          <div className="divide-y divide-border rounded-md border border-border">
            {watchlist.map((sym) => (
              <div key={sym} className="flex items-center justify-between gap-2 px-3 py-2 text-xs">
                <span className="font-mono font-semibold">{sym}</span>
                <div className="flex items-center gap-1">
                  <Button variant="ghost" size="icon" className="size-7" onClick={() => move(sym, -1)}>
                    <ArrowUp className="size-3.5" />
                  </Button>
                  <Button variant="ghost" size="icon" className="size-7" onClick={() => move(sym, 1)}>
                    <ArrowDown className="size-3.5" />
                  </Button>
                  <Button variant="ghost" size="icon" className="size-7 text-danger" onClick={() => remove(sym)}>
                    <X className="size-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

/* ---------------- News ---------------- */
function NewsTab() {
  const [sources, setSources] = useNewsSources();
  const [cats, setCats] = useNewsCategories();
  const [onlyWatched, setOnlyWatched] = useOnlyNewsForWatched();
  const plan = getCurrentPlan();
  const hasEdge = plan.trader === "trader-edge" || plan.trader === "trader-desk";

  return (
    <div className="space-y-4">
      <Section title="News sources" sub="Premium sources (Bloomberg, WSJ) require Edge or Desk.">
        <div className="grid gap-2 sm:grid-cols-2">
          {sources.map((s) => {
            const locked = !!s.premium && !hasEdge;
            return (
              <label key={s.id} className={cn(
                "flex items-center justify-between gap-3 rounded-md border border-border bg-background/40 px-3 py-2 text-xs",
                locked && "opacity-60",
              )}>
                <span className="flex items-center gap-2">
                  <span className="font-medium text-foreground">{s.name}</span>
                  {s.premium && (
                    <span className="rounded-sm bg-gold/10 px-1 text-[9px] font-mono uppercase tracking-wider text-gold">Edge+</span>
                  )}
                </span>
                <Switch
                  checked={s.enabled && !locked}
                  disabled={locked}
                  onCheckedChange={(v) =>
                    setSources(sources.map((x) => x.id === s.id ? { ...x, enabled: v } : x))
                  }
                />
              </label>
            );
          })}
        </div>
      </Section>

      <Section title="Topics">
        <div className="flex flex-wrap gap-2">
          {ALL_NEWS_CATEGORIES.map((c) => {
            const on = cats.includes(c);
            return (
              <button
                key={c}
                onClick={() => setCats(on ? cats.filter((x) => x !== c) : [...cats, c])}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs transition-colors",
                  on ? "border-gold/40 bg-gold/15 text-gold" : "border-border bg-background/40 text-muted-foreground hover:text-foreground",
                )}
              >
                {c}
              </button>
            );
          })}
        </div>
        <label className="flex items-center justify-between gap-3 rounded-md border border-border bg-background/40 px-3 py-2 text-xs">
          <span>Only show news mentioning my watched tickers</span>
          <Switch checked={onlyWatched} onCheckedChange={setOnlyWatched} />
        </label>
      </Section>
    </div>
  );
}

/* ---------------- Strategies ---------------- */
function StrategiesTab() {
  useFollowedOverlay();
  const [liveId, setLiveId] = useLiveTrackingStrategy();
  const followedIds = useMemo(() => getEffectiveFollowedIds(), []);
  const total = getTotalSlots();
  const nonFree = followedIds.filter((id) => !isFreeStrategy(id));

  return (
    <div className="space-y-4">
      <Section
        title="Followed strategies"
        sub={`${nonFree.length} of ${total === -1 ? "∞" : total} premium slots used. Free verified strategies don't count against your plan.`}
      >
        {followedIds.length === 0 ? (
          <p className="rounded-md border border-dashed border-border bg-background/40 p-4 text-center text-xs text-muted-foreground">
            You're not following anything yet.{" "}
            <Link to="/app/catalog" className="text-cyan underline-offset-2 hover:underline">
              Browse the catalog
            </Link>.
          </p>
        ) : (
          <div className="space-y-2">
            {followedIds.map((id) => {
              const s = strategies.find((x) => x.id === id);
              if (!s) return null;
              const free = isFreeStrategy(id);
              const isLive = liveId === id;
              return (
                <div key={id} className="flex items-center justify-between gap-3 rounded-md border border-border bg-background/40 px-3 py-2 text-xs">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Link to="/app/strategy/$id" params={{ id }} className="truncate font-medium hover:text-cyan">
                        {s.name}
                      </Link>
                      {free && <span className="rounded-sm bg-emerald/10 px-1 text-[9px] font-mono uppercase tracking-wider text-emerald">Free</span>}
                      {isLive && <span className="rounded-sm bg-cyan/10 px-1 text-[9px] font-mono uppercase tracking-wider text-cyan">Live tracking</span>}
                    </div>
                    <div className="text-[11px] text-muted-foreground capitalize">{s.assetClass}</div>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-[11px]"
                      onClick={() => setLiveId(isLive ? null : id)}
                    >
                      {isLive ? "Unpin" : "Set live"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7 text-danger"
                      onClick={() => { toggleFollow(id, false); window.location.reload(); }}
                      title="Unfollow"
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Section>
    </div>
  );
}

/* ---------------- Home Layout ---------------- */
function LayoutTab() {
  const [layout, setLayout] = useHomeLayout();
  const [hidden, setHidden] = useHiddenSections();

  const move = (s: HomeSection, dir: -1 | 1) => {
    const i = layout.indexOf(s);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= layout.length) return;
    const next = [...layout];
    [next[i], next[j]] = [next[j], next[i]];
    setLayout(next);
  };
  const toggleHidden = (s: HomeSection) => {
    setHidden(hidden.includes(s) ? hidden.filter((x) => x !== s) : [...hidden, s]);
  };
  const reset = () => { setLayout(DEFAULT_HOME_LAYOUT); setHidden([]); };

  const sectionLabel: Record<HomeSection, string> = {
    liveTracking: "Live Tracking",
    marketOverview: "Market Overview",
    myStrategies: "My Strategies",
    recentSignals: "Recent Signals",
    marketWire: "Market Wire",
    performance: "Performance",
  };

  return (
    <Section title="Home layout" sub="Reorder and toggle visibility of every zone on the Home page.">
      <div className="divide-y divide-border rounded-md border border-border">
        {layout.map((s) => {
          const visible = !hidden.includes(s);
          return (
            <div key={s} className="flex items-center justify-between gap-2 px-3 py-2 text-xs">
              <span className="font-medium text-foreground">{sectionLabel[s]}</span>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" className="size-7" onClick={() => move(s, -1)}><ArrowUp className="size-3.5" /></Button>
                <Button variant="ghost" size="icon" className="size-7" onClick={() => move(s, 1)}><ArrowDown className="size-3.5" /></Button>
                <Switch checked={visible} onCheckedChange={() => toggleHidden(s)} />
              </div>
            </div>
          );
        })}
      </div>
      <Button variant="outline" size="sm" onClick={reset}>Reset to default</Button>
    </Section>
  );
}

/* ---------------- Trading Defaults ---------------- */
function DefaultsTab() {
  const [acct, setAcct] = useAccountSize();
  const [risk, setRisk] = useRiskPerTrade();
  const [tf, setTf] = useDefaultTimeframe();
  const [chart, setChart] = useDefaultChartType();

  return (
    <Section title="Trading defaults" sub="Powers suggested position size on every signal and your default chart view.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Account size (USD)">
          <Input type="number" value={acct} onChange={(e) => setAcct(Number(e.target.value) || 0)} className="bg-background font-mono" />
        </Field>
        <Field label="Risk per trade (%)">
          <Input type="number" step="0.1" value={risk * 100} onChange={(e) => setRisk((Number(e.target.value) || 0) / 100)} className="bg-background font-mono" />
        </Field>
        <Field label="Default timeframe">
          <select value={tf} onChange={(e) => setTf(e.target.value)} className="h-9 w-full rounded-md border border-border bg-background px-2 text-xs">
            {["1m", "5m", "15m", "1H", "4H", "1D", "1W"].map((x) => <option key={x}>{x}</option>)}
          </select>
        </Field>
        <Field label="Default chart type">
          <select value={chart} onChange={(e) => setChart(e.target.value)} className="h-9 w-full rounded-md border border-border bg-background px-2 text-xs capitalize">
            {["candle", "line", "area"].map((x) => <option key={x}>{x}</option>)}
          </select>
        </Field>
      </div>
    </Section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

/* ---------------- Notifications ---------------- */
function NotificationsTab() {
  const [n, setN] = useNotifications();
  const items: { key: keyof typeof n; label: string; sub: string }[] = [
    { key: "signalFired", label: "New signal fired", sub: "When any followed strategy produces a new signal." },
    { key: "signalHitTarget", label: "Signal hit target", sub: "Closed positive — celebrate the win." },
    { key: "signalHitStop", label: "Signal hit stop", sub: "Closed negative — own the loss." },
    { key: "weeklySummary", label: "Weekly performance summary", sub: "Every Sunday: your week, in one digest." },
    { key: "strategyHWM", label: "Strategy new high water mark", sub: "When a followed strategy makes a new equity peak." },
    { key: "tickerNews", label: "News matching watched tickers", sub: "Real-time when your symbols hit the wire." },
  ];
  return (
    <Section title="Notifications">
      <div className="divide-y divide-border rounded-md border border-border">
        {items.map((it) => (
          <label key={it.key} className="flex items-center justify-between gap-3 px-3 py-2.5 text-xs">
            <div>
              <div className="font-medium text-foreground">{it.label}</div>
              <div className="text-[11px] text-muted-foreground">{it.sub}</div>
            </div>
            <Switch checked={n[it.key]} onCheckedChange={(v) => setN({ ...n, [it.key]: v })} />
          </label>
        ))}
      </div>
    </Section>
  );
}

void formatLimit; // silence unused
