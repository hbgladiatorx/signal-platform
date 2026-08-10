import { useEffect } from "react";
import { Link, Outlet, useRouterState, useNavigate } from "@tanstack/react-router";
import {
  Home, BookOpen, BarChart3, Signal as SignalIcon, Settings, Bell,
  User, ArrowRightLeft, Lock, Sparkles, Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { AssetFilterProvider, useAssetFilter, ASSET_OPTIONS } from "@/lib/asset-filter";

import { PlanBadge } from "@/components/billing/PlanBadge";
import { getCurrentPlan } from "@/lib/api/billing";
import { useAuth } from "@/hooks/use-auth";

type NavItem = { to: string; label: string; icon: typeof Home };

// Trader dock is the core loop only — Today → Catalog → Signals → Perf.
// Secondary surfaces (Markets, Agent, Settings) live in the account menu so the
// dock stays uncluttered and every screen has an obvious place in the flow.
const traderNav: NavItem[] = [
  { to: "/app/home", label: "Today", icon: Home },
  { to: "/app/catalog", label: "Catalog", icon: BookOpen },
  { to: "/app/signals", label: "Signals", icon: SignalIcon },
  { to: "/app/performance", label: "Perf", icon: BarChart3 },
];

// Studio is copilot-first: the copilot drives build → backtest → validate →
// forward, so those individual tabs collapse into it. Live monitoring and
// settings stay separate. (Older pages remain reachable by URL.)
const studioNav: NavItem[] = [
  { to: "/studio/home", label: "Overview", icon: Home },
  { to: "/studio/copilot", label: "Copilot", icon: Sparkles },
  { to: "/studio/live", label: "Live", icon: Activity },
  { to: "/studio/settings", label: "Settings", icon: Settings },
];


export function AppShell({ mode = "trader" }: { mode?: "trader" | "studio" }) {
  return (
    <AssetFilterProvider>
      <Shell mode={mode} />
    </AssetFilterProvider>
  );
}

function Shell({ mode }: { mode: "trader" | "studio" }) {
  const pathname = useRouterState({ select: (r) => r.location.pathname });
  const navigate = useNavigate();
  const nav = mode === "studio" ? studioNav : traderNav;
  const isStudio = mode === "studio";
  const { user } = useAuth();
  // Real signed-in handle from the Supabase session; honest fallback if absent.
  const handle = user?.email ? `@${user.email.split("@")[0]}` : "your account";

  useEffect(() => {
    if (isStudio) document.documentElement.classList.add("studio-mode");
    else document.documentElement.classList.remove("studio-mode");
    return () => document.documentElement.classList.remove("studio-mode");
  }, [isStudio]);

  return (
    <div className={cn("relative flex min-h-screen w-full flex-col bg-background mode-fade")} key={mode}>
      {/* Top header */}
      <header className="sticky top-0 z-30 border-b border-border bg-background/70 backdrop-blur">
        <div className="flex h-14 items-center gap-3 px-4 md:px-6">
          <Link
            to={isStudio ? "/studio/copilot" : "/app/home"}
            className="flex shrink-0 items-center gap-2 font-semibold tracking-tight"
          >
            <div className={cn("grid size-7 place-items-center rounded-md font-bold", isStudio ? "bg-violet/15 text-violet" : "bg-cyan/15 text-cyan")}>
              B
            </div>
            <span className="hidden sm:inline">
              Bayn{isStudio && (
                <span className="ml-1.5 rounded-md bg-violet/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest text-violet">
                  Studio
                </span>
              )}
            </span>
          </Link>

          {isStudio && (
            <TooltipProvider delayDuration={120}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="hidden items-center gap-1 rounded-full border border-violet/30 bg-violet/10 px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider text-violet md:inline-flex">
                    <Lock className="size-3" /> Private to you
                  </span>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="max-w-xs">
                  Your Studio is private. Strategies, backtests, and personal signals stay on your account until you submit them to the Bayn catalog.
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}

          {/* Notifications. No notifications backend yet, so no count is shown
              (an honest empty bell rather than a fabricated badge). */}
          <Button variant="ghost" size="icon" aria-label="Notifications" className="relative ml-auto">
            <Bell className="size-5" />
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Account menu" className="rounded-full">
                <div className={cn("grid size-8 place-items-center rounded-full", isStudio ? "bg-violet/15 text-violet" : "bg-cyan/15 text-cyan")}>
                  <User className="size-4" />
                </div>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-60">
              <DropdownMenuLabel>
                <div className="flex items-center gap-1.5">
                  Signed in as <span className={isStudio ? "font-mono text-violet" : "font-mono text-cyan"}>{handle}</span>
                </div>
                <div className="mt-1.5 flex items-center gap-1.5">
                  <PlanBadge tier={isStudio ? getCurrentPlan().developer : getCurrentPlan().trader} />
                  <span className="text-[10px] font-normal text-muted-foreground">
                    {isStudio ? "Your private Studio" : "Trader account"}
                  </span>
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              {!isStudio ? (
                <DropdownMenuItem onSelect={() => navigate({ to: "/studio/home" })}>
                  <ArrowRightLeft className="mr-2 size-4 text-violet" /> Open my Studio
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem onSelect={() => navigate({ to: "/app/home" })}>
                  <ArrowRightLeft className="mr-2 size-4 text-cyan" /> Back to Trader
                </DropdownMenuItem>
              )}
              {!isStudio && (
                <>
                  <DropdownMenuItem asChild>
                    <Link to="/app/markets">Markets &amp; news</Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <Link to="/app/agent">AI Agent (preview)</Link>
                  </DropdownMenuItem>
                </>
              )}
              <DropdownMenuItem asChild>
                <Link to={isStudio ? "/studio/pricing" : "/app/pricing"}>Plan & billing</Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link to={isStudio ? "/studio/settings" : "/app/settings"}>Settings</Link>
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={async () => {
                  const { supabase } = await import("@/integrations/supabase/client");
                  const { resetAllPrefs } = await import("@/lib/user-prefs");
                  const { resetCurrentPlan } = await import("@/lib/api/billing");
                  await supabase.auth.signOut();
                  // Clear local prefs so the next account that signs in starts blank.
                  resetAllPrefs();
                  resetCurrentPlan();
                  navigate({ to: "/" });
                }}
              >
                Sign out
              </DropdownMenuItem>

            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        {/* Asset-class filter — trader only, cascades through context.
            The always-scrolling ticker tape moved to the Markets tab to keep
            every screen calm. */}
        {!isStudio && <AssetChipRow />}

      </header>

      <main className="min-w-0 flex-1 pb-32">
        <Outlet />
      </main>

      {/* Bottom dock — prominent floating pill */}
      <nav
        className="pointer-events-none fixed inset-x-0 bottom-5 z-40 flex justify-center px-3"
        aria-label="Primary"
      >
        {/* Halo glow behind the dock for prominence */}
        <div
          aria-hidden
          className="pointer-events-none absolute bottom-1 left-1/2 h-16 w-[min(640px,92vw)] -translate-x-1/2 rounded-full blur-2xl opacity-70"
          style={{
            background: isStudio
              ? "radial-gradient(closest-side, color-mix(in oklab, var(--violet) 45%, transparent), transparent 75%)"
              : "radial-gradient(closest-side, color-mix(in oklab, var(--cyan) 45%, transparent), transparent 75%)",
          }}
        />
        <div
          className={cn(
            "pointer-events-auto relative flex max-w-[96vw] items-center gap-1 overflow-x-auto rounded-full border-2 p-2 backdrop-blur-2xl",
            isStudio ? "border-violet/40" : "border-cyan/40",
          )}
          style={{
            background: "color-mix(in oklab, var(--background) 78%, transparent)",
            boxShadow: isStudio
              ? "0 20px 50px -12px color-mix(in oklab, var(--violet) 45%, transparent), 0 0 0 1px color-mix(in oklab, var(--violet) 25%, transparent) inset"
              : "0 20px 50px -12px color-mix(in oklab, var(--cyan) 45%, transparent), 0 0 0 1px color-mix(in oklab, var(--cyan) 25%, transparent) inset",
          }}
        >
          {nav.map((item) => {
            const active = pathname === item.to || pathname.startsWith(item.to + "/");
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "group relative flex items-center gap-1.5 rounded-full px-3.5 py-2.5 text-[12px] font-medium tracking-tight transition-all",
                  active
                    ? isStudio
                      ? "bg-violet text-violet-foreground shadow-lg shadow-violet/40"
                      : "bg-cyan text-cyan-foreground shadow-lg shadow-cyan/40"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
              >
                <Icon className="size-[16px] shrink-0" />
                <span className="hidden sm:inline">{item.label}</span>
                {active && (
                  <span className={cn(
                    "absolute -top-1 left-1/2 size-1.5 -translate-x-1/2 rounded-full",
                    isStudio ? "bg-violet" : "bg-cyan",
                  )} />
                )}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}

function AssetChipRow() {
  const { assetClass, setAssetClass } = useAssetFilter();
  return (
    <div className="flex items-center gap-1.5 overflow-x-auto border-t border-border/60 px-4 py-2 md:px-6">
      <span className="mr-1 hidden text-[10px] font-mono uppercase tracking-[0.18em] text-muted-foreground sm:inline">
        Asset
      </span>
      {ASSET_OPTIONS.map((opt) => {
        const active = assetClass === opt.key;
        return (
          <button
            key={opt.key}
            onClick={() => setAssetClass(opt.key)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
              active
                ? "border-cyan/40 bg-cyan/15 text-cyan"
                : "border-border bg-elevated text-muted-foreground hover:text-foreground",
            )}
          >
            <span className={cn("size-1.5 rounded-full", opt.dot)} />
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
