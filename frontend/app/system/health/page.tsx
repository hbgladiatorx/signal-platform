"use client";

import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import type { HealthResponse } from "@/lib/types";

export default function SystemHealthPage() {
  const api = useApi();

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<HealthResponse>("/health"),
    refetchInterval: 10_000,
  });

  return (
    <AppShell title="System Health">
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="text-base font-semibold text-navy-700">API status</h2>
        {healthQuery.isLoading && (
          <p className="mt-2 text-sm text-gray-500">Checking…</p>
        )}
        {healthQuery.data && (
          <div className="mt-3 space-y-1 text-sm">
            <div>
              <span className="text-gray-500">Status: </span>
              <span
                className={
                  healthQuery.data.status === "alive"
                    ? "text-green-600"
                    : "text-yellow-600"
                }
              >
                {healthQuery.data.status}
              </span>
            </div>
            <div className="font-mono text-xs text-gray-500">
              {healthQuery.data.ts}
            </div>
          </div>
        )}
        {healthQuery.error && (
          <p className="mt-2 text-sm text-red-600">
            Health check failed: {(healthQuery.error as Error).message}
          </p>
        )}
      </div>

      <div className="mt-6 rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="text-base font-semibold text-navy-700">
          Phase 1 — Step 12
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          The fuller system health view (ingestion freshness, persistence
          worker rates, database statistics) lands in Step 12.
        </p>
      </div>
    </AppShell>
  );
}
