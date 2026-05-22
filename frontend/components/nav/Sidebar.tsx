"use client";

import {
  Activity,
  BarChart3,
  Database,
  LayoutDashboard,
  Settings,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  href: string;
  icon: typeof LayoutDashboard;
}

const navItems: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Instruments", href: "/instruments", icon: Database },
  { label: "Strategies", href: "/strategies", icon: Workflow },
  { label: "System Health", href: "/system/health", icon: Activity },
  { label: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-60 flex-col border-r border-gray-200 bg-white">
      <div className="flex h-14 items-center gap-2 border-b border-gray-200 px-4">
        <BarChart3 className="h-5 w-5 text-gold-500" />
        <span className="font-semibold text-navy-700">Signal Platform</span>
      </div>

      <nav className="flex-1 space-y-0.5 p-2">
        {navItems.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/dashboard" && pathname.startsWith(item.href));
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-navy-50 text-navy-700"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-900",
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-gray-200 p-3 text-xs text-gray-400">
        v0.1.0 · Phase 1
      </div>
    </aside>
  );
}
