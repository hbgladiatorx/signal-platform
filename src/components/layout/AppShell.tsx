import { useState } from "react";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import {
  Home, BookOpen, BarChart3, Signal as SignalIcon, Settings, Bell, Search,
  Menu, FlaskConical, Plus, Wallet, FileText, ChevronsLeft, User,
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
  { to: "/home",        label: "Home",        icon: Home },
  { to: "/catalog",     label: "Catalog",     icon: BookOpen },
  { to: "/performance", label: "Performance", icon: BarChart3 },
  { to: "/signals",     label: "Signals",     icon: SignalIcon },
  { to: "/settings",    label: "Settings",    icon: Settings },
];

const studioNav: NavItem[] = [
  { to: "/studio",          label: "My Strategies", icon: FlaskConical },
  { to: "/studio/new",      label: "New Strategy",  icon: Plus },
  { to: "/studio/earnings", label: "Earnings",      icon: Wallet },
  { to: "/studio/docs",     label: "Docs",          icon: FileText },
  { to: "/settings",        label: "Settings",      icon: Settings },
];

export function AppShell({ mode = "trader" }: { mode?: "trader" | "studio" }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = useRouterState({ select: (r) => r.location.pathname });
  const nav = mode === "studio" ? studioNav : traderNav;

  return (
    <div className={cn("flex min-h-screen w-full bg-background", mode === "studio" && "font-[ui-sans-serif]")}>
      {/* Sidebar */}
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] md:flex",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div className="flex h-14 items-center gap-2 border-b border-sidebar-border px-4">
          <Link to="/home" className="flex items-center gap-2 font-semibold tracking-tight">
            <div className="grid size-7 place-items-center rounded-md bg-cyan/15 text-cyan">
              <span className="text-sm font-bold">B</span>
            </div>
            {!collapsed && (
              <span>
                Bayn {mode === "studio" && <span className="ml-1 text-[10px] uppercase tracking-widest text-gold">Studio</span>}
              </span>
            )}
          </Link>
        </div>
        <nav className="flex-1 space-y-0.5 p-2">
          {nav.map((item) => {
            const active = pathname === item.to || (item.to !== "/studio" && pathname.startsWith(item.to + "/"));
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground hover:bg-sidebar-accent/60",
                )}
              >
                <Icon className="size-4 shrink-0" />
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

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setMobileOpen(false)}>
          <div className="absolute inset-0 bg-background/80 backdrop-blur" />
          <aside className="absolute left-0 top-0 h-full w-60 border-r border-sidebar-border bg-sidebar p-2">
            <div className="px-2 py-3 font-semibold">Bayn</div>
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

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-background/80 px-4 backdrop-blur">
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setMobileOpen(true)}>
            <Menu className="size-5" />
          </Button>
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Search strategies, symbols…" className="h-9 border-border bg-elevated pl-8" />
          </div>
          <Button variant="ghost" size="icon" className="relative">
            <Bell className="size-5" />
            <span className="absolute right-1.5 top-1.5 grid size-4 place-items-center rounded-full bg-danger text-[10px] font-bold text-danger-foreground">3</span>
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="rounded-full">
                <div className="grid size-8 place-items-center rounded-full bg-cyan/15 text-cyan">
                  <User className="size-4" />
                </div>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>Signed in as <span className="font-mono text-cyan">@trader</span></DropdownMenuLabel>
              <DropdownMenuSeparator />
              {mode === "trader" ? (
                <DropdownMenuItem asChild><Link to="/studio">Switch to Studio</Link></DropdownMenuItem>
              ) : (
                <DropdownMenuItem asChild><Link to="/home">Switch to Trader</Link></DropdownMenuItem>
              )}
              <DropdownMenuItem asChild><Link to="/settings">Settings</Link></DropdownMenuItem>
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
