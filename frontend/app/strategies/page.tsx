"use client";

import { AppShell } from "@/components/nav/AppShell";

export default function StrategiesPage() {
  return (
    <AppShell title="Strategies">
      <div className="rounded-lg border border-gray-200 bg-white p-8">
        <h2 className="text-base font-semibold text-navy-700">Phase 2</h2>
        <p className="mt-2 text-sm text-gray-600">
          Strategy authoring, backtesting, and the paper/shadow/live
          lifecycle are scheduled for Phase 2. The infrastructure that
          powers them (canonical strategy schema, backtest engine, paper
          trader) hasn&rsquo;t been built yet.
        </p>
      </div>
    </AppShell>
  );
}
