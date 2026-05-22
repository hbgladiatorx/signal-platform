"use client";

import { type ReactNode } from "react";

import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { Header } from "@/components/nav/Header";
import { Sidebar } from "@/components/nav/Sidebar";

/**
 * The shell for every authenticated page.
 *
 * Wraps the page in ProtectedRoute (so unauthenticated users are
 * redirected to Auth0), renders the sidebar and header, and gives
 * the page a scrollable main area.
 */
export function AppShell({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <ProtectedRoute>
      <div className="flex h-screen bg-gray-50">
        <Sidebar />
        <div className="flex flex-1 flex-col overflow-hidden">
          <Header title={title} />
          <main className="flex-1 overflow-y-auto p-6">{children}</main>
        </div>
      </div>
    </ProtectedRoute>
  );
}
