"use client";

import { useAuth0 } from "@auth0/auth0-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { APIKeysSection } from "@/components/settings/APIKeysSection";
import { DataSourcesSection } from "@/components/settings/DataSourcesSection";
import { InstrumentsSection } from "@/components/settings/InstrumentsSection";
import { ProfileSection } from "@/components/settings/ProfileSection";
import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import { cn } from "@/lib/utils";
import type { ProfileResponse, ProfileSync } from "@/lib/types";

type Tab = "profile" | "api-keys" | "instruments" | "data-sources";

const TABS: { id: Tab; label: string }[] = [
  { id: "profile", label: "Profile" },
  { id: "api-keys", label: "API Keys" },
  { id: "instruments", label: "Instruments" },
  { id: "data-sources", label: "Data Sources" },
];

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("profile");
  const { user } = useAuth0();
  const api = useApi();
  const qc = useQueryClient();

  // Sync email/name from Auth0 ID token to backend profile on first mount.
  const syncedRef = useRef(false);
  const syncMutation = useMutation({
    mutationFn: (body: ProfileSync) =>
      api.post<ProfileResponse>("/settings/profile/sync", body),
    onSuccess: (data) => {
      qc.setQueryData(["settings", "profile"], data);
    },
  });

  useEffect(() => {
    if (syncedRef.current) return;
    if (!user) return;
    if (!user.email && !user.name) return;
    syncedRef.current = true;
    syncMutation.mutate({
      email: user.email ?? undefined,
      name: user.name ?? undefined,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  return (
    <AppShell title="Settings">
      <div className="space-y-6">
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex gap-6 overflow-x-auto">
            {TABS.map((t) => (
              <TabButton
                key={t.id}
                active={tab === t.id}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </TabButton>
            ))}
          </nav>
        </div>

        {tab === "profile" && <ProfileSection />}
        {tab === "api-keys" && <APIKeysSection />}
        {tab === "instruments" && <InstrumentsSection />}
        {tab === "data-sources" && <DataSourcesSection />}
      </div>
    </AppShell>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "whitespace-nowrap border-b-2 px-1 py-3 text-sm font-medium transition-colors",
        active
          ? "border-navy-600 text-navy-700"
          : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700",
      )}
    >
      {children}
    </button>
  );
}
