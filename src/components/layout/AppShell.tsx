import { useEffect } from "react";
import { Link, Outlet, useRouterState, useNavigate } from "@tanstack/react-router";
import {
  Home, BookOpen, BarChart3, Signal as SignalIcon, Settings, Bell, Search,
  Wallet, FileText, User, Layers, GitBranch, Inbox as InboxIcon, ArrowRightLeft, Lock, Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { AssetFilterProvider, useAssetFilter, ASSET_OPTIONS } from "@/lib/asset-filter";
import { MarketTicker } from "@/components/common/MarketTicker";

type NavItem = { to: string; label: string; icon: typeof Home };

const traderNav: NavItem[] = [
  { to: "/app/home", label: "Home", icon: Home },
  { to: "/app/catalog", label: "Catalog", icon: BookOpen },
  { to: "/app/signals", label: "Signals", icon: SignalIcon },
  { to: "/app/performance", label: "Perf", icon: BarChart3 },
  { to: "/app/agent", label: "Agent", icon: Sparkles },
  { to: "/app/settings", label: "Settings", icon: Settings },
];

const studioNav: NavItem[] = [
  { to: "/studio/home", label: "My Studio", icon: Home },
  { to: "/studio/strategies", label: "Strategies", icon: Layers },
  { to: "/studio/builder/new", label: "Builder", icon: GitBranch },
  { to: "/studio/backtests", label: "Backtests", icon: BarChart3 },
  { to: "/studio/signals", label: "Signals", icon: SignalIcon },
  { to: "/studio/earnings", label: "Earnings", icon: Wallet },
  { to: "/studio/submissions", label: "Submit", icon: InboxIcon },
  { to: "/studio/docs", label: "Docs", icon: FileText },
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
            to={isStudio ? "/studio/home" : "/app/home"}
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

          <div className="relative ml-auto hidden max-w-sm flex-1 md:block">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder={isStudio ? "Search strategies, nodes…" : "Search strategies, symbols…"}
              className="h-9 border-border bg-elevated pl-8"
            />
          </div>

          <Button variant="ghost" size="icon" className="relative ml-auto md:ml-0">
            <Bell className="size-5" />
            <span className={cn(
              "absolute right-1.5 top-1.5 grid size-4 place-items-center rounded-full text-[10px] font-bold",
              isStudio ? "bg-violet text-violet-foreground" : "bg-danger text-danger-foreground",
            )}>3</span>
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="rounded-full">
                <div className={cn("grid size-8 place-items-center rounded-full", isStudio ? "bg-violet/15 text-violet" : "bg-cyan/15 text-cyan")}>
                  <User className="size-4" />
                </div>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>
                Signed in as <span className={isStudio ? "font-mono text-violet" : "font-mono text-cyan"}>@trader</span>
                <div className="mt-0.5 text-[10px] font-normal text-muted-foreground">
                  {isStudio ? "Your private Studio" : "Trader account"}
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
              <DropdownMenuItem asChild>
                <Link to={isStudio ? "/studio/settings" : "/app/settings"}>Settings</Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild><Link to="/">Sign out</Link></DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {/* Asset-class filter — trader only, cascades through context */}
        {!isStudio && <AssetChipRow />}

        {/* Bloomberg-style market ticker — trader only */}
        {!isStudio && <MarketTicker />}
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
