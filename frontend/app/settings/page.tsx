"use client";

import { useAuth0 } from "@auth0/auth0-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { APIKeysSection } from "@/components/settings/APIKeysSection";
import { ProfileSection } from "@/components/settings/ProfileSection";
import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import { cn } from "@/lib/utils";
import type { ProfileResponse, ProfileSync } from "@/lib/types";

type Tab = "profile" | "api-keys";

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("profile");
  const { user } = useAuth0();
  const api = useApi();
  const qc = useQueryClient();

  // Sync email/name from the Auth0 ID token to the backend profile.
  // Backend uses COALESCE, so existing values are not overwritten.
  // We only fire this once per page mount.
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
          <nav className="-mb-px flex gap-6">
            <TabButton
              active={tab === "profile"}
              onClick={() => setTab("profile")}
            >
              Profile
            </TabButton>
            <TabButton
              active={tab === "api-keys"}
              onClick={() => setTab("api-keys")}
            >
              API Keys
            </TabButton>
          </nav>
        </div>

        {tab === "profile" && <ProfileSection />}
        {tab === "api-keys" && <APIKeysSection />}
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
        "border-b-2 px-1 py-3 text-sm font-medium transition-colors",
        active
          ? "border-navy-600 text-navy-700"
          : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700",
      )}
    >
      {children}
    </button>
  );
}
