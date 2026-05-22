"use client";

import { useAuth0 } from "@auth0/auth0-react";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import type { MeResponse } from "@/lib/types";

export default function SettingsPage() {
  const { user } = useAuth0();
  const api = useApi();

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<MeResponse>("/me"),
  });

  return (
    <AppShell title="Settings">
      <div className="space-y-6">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h2 className="text-base font-semibold text-navy-700">
            Your account
          </h2>
          <div className="mt-4 grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
            <Row label="Email" value={user?.email ?? "—"} />
            <Row label="Name" value={user?.name ?? "—"} />
            <Row label="Auth0 sub" value={user?.sub ?? "—"} mono />
            <Row
              label="Email verified"
              value={user?.email_verified ? "Yes" : "No"}
            />
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h2 className="text-base font-semibold text-navy-700">
            Backend claims (/me)
          </h2>
          <p className="mt-1 text-xs text-gray-500">
            Returned by the API when this page calls /me with your JWT.
            Useful to verify end-to-end auth.
          </p>
          {meQuery.isLoading && (
            <p className="mt-3 text-sm text-gray-500">Loading…</p>
          )}
          {meQuery.error && (
            <p className="mt-3 text-sm text-red-600">
              {(meQuery.error as Error).message}
            </p>
          )}
          {meQuery.data && (
            <pre className="mt-3 overflow-x-auto rounded-md bg-gray-50 p-4 text-xs text-gray-700">
              {JSON.stringify(meQuery.data, null, 2)}
            </pre>
          )}
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h2 className="text-base font-semibold text-navy-700">Phase 1</h2>
          <p className="mt-2 text-sm text-gray-600">
            Profile + API key management (Tier 1) lands in Step 13.
            Instrument and data-source selection (Tier 2) in Step 14.
            Today this page is here so the route exists.
          </p>
        </div>
      </div>
    </AppShell>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div
        className={
          mono
            ? "mt-1 break-all font-mono text-xs text-gray-800"
            : "mt-1 text-sm text-gray-800"
        }
      >
        {value}
      </div>
    </div>
  );
}
