import { useState, useEffect } from "react";
import { Link, Outlet, useRouterState, useNavigate } from "@tanstack/react-router";
import {
  Home, BookOpen, BarChart3, Signal as SignalIcon, Settings, Bell, Search,
  Menu, FlaskConical, Wallet, FileText, ChevronsLeft, User, Layers,
  GitBranch, Inbox as InboxIcon, ArrowRightLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type NavItem = { to: string; label: string; icon: typeof Home };

const traderNav: NavItem[] = [
  { to: "/app/home", label: "Home", icon: Home },
  { to: "/app/catalog", label: "Catalog", icon: BookOpen },
  { to: "/app/signals", label: "Signals", icon: SignalIcon },
  { to: "/app/performance", label: "Performance", icon: BarChart3 },
  { to: "/app/settings", label: "Settings", icon: Settings },
];

const studioNav: NavItem[] = [
  { to: "/studio/home", label: "Dashboard", icon: Home },
  { to: "/studio/strategies", label: "My Strategies", icon: Layers },
  { to: "/studio/builder/new", label: "Builder", icon: GitBranch },
  { to: "/studio/backtests", label: "Backtests", icon: BarChart3 },
  { to: "/studio/signals", label: "Live Signals", icon: SignalIcon },
  { to: "/studio/earnings", label: "Earnings", icon: Wallet },
  { to: "/studio/submissions", label: "Submissions", icon: InboxIcon },
  { to: "/studio/docs", label: "Docs", icon: FileText },
  { to: "/studio/settings", label: "Settings", icon: Settings },
];

export function AppShell({ mode = "trader" }: { mode?: "trader" | "studio" }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = useRouterState({ select: (r) => r.location.pathname });
  const navigate = useNavigate();
  const nav = mode === "studio" ? studioNav : traderNav;
  const accent = mode === "studio" ? "violet" : "cyan";

  useEffect(() => {
    if (mode === "studio") document.documentElement.classList.add("studio-mode");
    else document.documentElement.classList.remove("studio-mode");
    return () => document.documentElement.classList.remove("studio-mode");
  }, [mode]);

  return (
    <div className={cn("flex min-h-screen w-full bg-background mode-fade")} key={mode}>
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] md:flex",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div className="flex h-14 items-center gap-2 border-b border-sidebar-border px-4">
          <Link to={mode === "studio" ? "/studio/home" : "/app/home"} className="flex items-center gap-2 font-semibold tracking-tight">
            <div className={cn("grid size-7 place-items-center rounded-md font-bold", mode === "studio" ? "bg-violet/15 text-violet" : "bg-cyan/15 text-cyan")}>
              B
            </div>
            {!collapsed && (
              <span>
                Bayn {mode === "studio" && <span className="ml-1 rounded-md bg-violet/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest text-violet">Studio</span>}
              </span>
            )}
          </Link>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {nav.map((item) => {
            const active = pathname === item.to || pathname.startsWith(item.to + "/");
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? cn("bg-sidebar-accent text-sidebar-accent-foreground", accent === "cyan" ? "border-l-2 border-cyan" : "border-l-2 border-violet")
                    : "text-sidebar-foreground hover:bg-sidebar-accent/60",
                )}
              >
                <Icon className={cn("size-4 shrink-0", active && (accent === "cyan" ? "text-cyan" : "text-violet"))} />
                {!collapsed && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-sidebar-border p-2">
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-xs text-muted-foreground hover:bg-sidebar-accent/60"
          >
            <ChevronsLeft className={cn("size-4 transition-transform", collapsed && "rotate-180")} />
            {!collapsed && "Collapse"}
          </button>
        </div>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setMobileOpen(false)}>
          <div className="absolute inset-0 bg-background/80 backdrop-blur" />
          <aside className="absolute left-0 top-0 h-full w-60 border-r border-sidebar-border bg-sidebar p-2">
            <div className="px-2 py-3 font-semibold">Bayn{mode === "studio" && " Studio"}</div>
            {nav.map((item) => {
              const Icon = item.icon;
              return (
                <Link key={item.to} to={item.to} onClick={() => setMobileOpen(false)}
                  className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-sidebar-foreground hover:bg-sidebar-accent/60">
                  <Icon className="size-4" /> {item.label}
                </Link>
              );
            })}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-background/80 px-4 backdrop-blur">
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setMobileOpen(true)}>
            <Menu className="size-5" />
          </Button>
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder={mode === "studio" ? "Search strategies, nodes…" : "Search strategies, symbols…"} className="h-9 border-border bg-elevated pl-8" />
          </div>
          <Button variant="ghost" size="icon" className="relative">
            <Bell className="size-5" />
            <span className={cn("absolute right-1.5 top-1.5 grid size-4 place-items-center rounded-full text-[10px] font-bold", mode === "studio" ? "bg-violet text-violet-foreground" : "bg-danger text-danger-foreground")}>3</span>
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="rounded-full">
                <div className={cn("grid size-8 place-items-center rounded-full", mode === "studio" ? "bg-violet/15 text-violet" : "bg-cyan/15 text-cyan")}>
                  <User className="size-4" />
                </div>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>Signed in as <span className={mode === "studio" ? "font-mono text-violet" : "font-mono text-cyan"}>@trader</span></DropdownMenuLabel>
              <DropdownMenuSeparator />
              {mode === "trader" ? (
                <DropdownMenuItem onSelect={() => navigate({ to: "/studio/home" })}>
                  <ArrowRightLeft className="mr-2 size-4 text-violet" /> Switch to Studio
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem onSelect={() => navigate({ to: "/app/home" })}>
                  <ArrowRightLeft className="mr-2 size-4 text-cyan" /> Switch to Trader
                </DropdownMenuItem>
              )}
              <DropdownMenuItem asChild><Link to={mode === "studio" ? "/studio/settings" : "/app/settings"}>Settings</Link></DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild><Link to="/">Sign out</Link></DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        <main className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
