"use client";

import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import type { Instrument } from "@/lib/types";

export default function DashboardPage() {
  const api = useApi();

  const instrumentsQuery = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/instruments"),
  });

  return (
    <AppShell title="Dashboard">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
        <StatCard
          label="Instruments tracked"
          value={
            instrumentsQuery.isLoading
              ? "…"
              : instrumentsQuery.data?.length.toString() ?? "—"
          }
          hint="Live market data ingestion"
        />
        <StatCard label="Strategies running" value="0" hint="Phase 2" />
        <StatCard label="Open positions" value="0" hint="Phase 4 (live)" />
      </div>

      <div className="mt-8 rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="text-base font-semibold text-navy-700">
          Phase 1 in progress
        </h3>
        <p className="mt-2 text-sm text-gray-600">
          The platform currently ingests live trades and quotes from
          Binance.US into TimescaleDB. The API serves this data; the
          frontend you&rsquo;re looking at is the navigation shell. Charts
          land in Step 11; strategies and backtests in Phase 2.
        </p>
      </div>
    </AppShell>
  );
}

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <div className="text-xs uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-navy-700">{value}</div>
      {hint && <div className="mt-1 text-xs text-gray-400">{hint}</div>}
    </div>
  );
}
