"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useApi } from "@/lib/useApi";
import { cn } from "@/lib/utils";
import type { ProfileResponse, ProfileUpdate } from "@/lib/types";

const COMMON_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Detroit",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Tokyo",
  "Asia/Singapore",
  "Australia/Sydney",
];

const THEMES: Array<"light" | "dark" | "system"> = ["light", "dark", "system"];

export function ProfileSection() {
  const api = useApi();
  const qc = useQueryClient();

  const profileQuery = useQuery({
    queryKey: ["settings", "profile"],
    queryFn: () => api.get<ProfileResponse>("/settings/profile"),
  });

  const [draft, setDraft] = useState<ProfileUpdate>({});
  const [savedFlash, setSavedFlash] = useState(false);

  // Sync draft when profile loads/changes
  useEffect(() => {
    if (profileQuery.data) {
      setDraft({
        name: profileQuery.data.name ?? "",
        timezone: profileQuery.data.timezone,
        theme: profileQuery.data.theme,
        notifications_enabled: profileQuery.data.notifications_enabled,
      });
    }
  }, [profileQuery.data]);

  const updateMutation = useMutation({
    mutationFn: (update: ProfileUpdate) =>
      api.put<ProfileResponse>("/settings/profile", update),
    onSuccess: (data) => {
      qc.setQueryData(["settings", "profile"], data);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2_000);
    },
  });

  const dirty =
    profileQuery.data !== undefined &&
    ((draft.name ?? "") !== (profileQuery.data.name ?? "") ||
      draft.timezone !== profileQuery.data.timezone ||
      draft.theme !== profileQuery.data.theme ||
      draft.notifications_enabled !==
        profileQuery.data.notifications_enabled);

  if (profileQuery.isLoading) {
    return <div className="p-6 text-sm text-gray-500">Loading profile…</div>;
  }
  if (profileQuery.error) {
    return (
      <div className="p-6 text-sm text-red-600">
        Failed to load profile: {(profileQuery.error as Error).message}
      </div>
    );
  }

  const profile = profileQuery.data!;

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="text-base font-semibold text-navy-700">Identity</h2>
        <div className="mt-4 grid grid-cols-1 gap-4 text-sm md:grid-cols-2">
          <ReadOnlyField label="Email" value={profile.email ?? "—"} />
          <ReadOnlyField label="Auth0 ID" value={profile.auth0_sub} mono />
        </div>
        <p className="mt-3 text-xs text-gray-500">
          Email and identity come from your authentication provider and
          can&rsquo;t be changed here.
        </p>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="text-base font-semibold text-navy-700">Profile</h2>

        <div className="mt-4 space-y-4">
          <LabeledInput
            label="Display name"
            value={draft.name ?? ""}
            onChange={(v) => setDraft({ ...draft, name: v })}
            placeholder="How you want to be addressed"
          />

          <LabeledSelect
            label="Timezone"
            value={draft.timezone ?? "UTC"}
            onChange={(v) => setDraft({ ...draft, timezone: v })}
            options={COMMON_TIMEZONES.map((tz) => ({ value: tz, label: tz }))}
            help="Affects display of timestamps in the UI."
          />

          <LabeledSelect
            label="Theme"
            value={draft.theme ?? "light"}
            onChange={(v) =>
              setDraft({
                ...draft,
                theme: v as "light" | "dark" | "system",
              })
            }
            options={THEMES.map((t) => ({
              value: t,
              label: t.charAt(0).toUpperCase() + t.slice(1),
            }))}
            help="Dark mode arrives in a future release; today the setting is stored but not visually applied."
          />

          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
              <input
                type="checkbox"
                checked={draft.notifications_enabled ?? false}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    notifications_enabled: e.target.checked,
                  })
                }
                className="h-4 w-4 rounded border-gray-300 text-navy-600 focus:ring-navy-500"
              />
              Email notifications
            </label>
            <p className="ml-6 text-xs text-gray-500">
              Reserved for Phase 4+ when alerts ship.
            </p>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          {savedFlash && (
            <span className="text-xs text-green-600">Saved</span>
          )}
          <button
            type="button"
            onClick={() => updateMutation.mutate(draft)}
            disabled={!dirty || updateMutation.isPending}
            className={cn(
              "rounded-md px-4 py-2 text-sm font-medium text-white transition-colors",
              !dirty || updateMutation.isPending
                ? "cursor-not-allowed bg-navy-300"
                : "bg-navy-600 hover:bg-navy-700",
            )}
          >
            {updateMutation.isPending ? "Saving…" : "Save changes"}
          </button>
        </div>

        {updateMutation.isError && (
          <div className="mt-3 text-sm text-red-600">
            {(updateMutation.error as Error).message}
          </div>
        )}
      </div>
    </div>
  );
}

// ----- small inputs -----

function ReadOnlyField({
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
            ? "mt-1 break-all font-mono text-xs text-gray-700"
            : "mt-1 text-sm text-gray-800"
        }
      >
        {value}
      </div>
    </div>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-gray-700">
        {label}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
      />
    </div>
  );
}

function LabeledSelect({
  label,
  value,
  onChange,
  options,
  help,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  help?: string;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-gray-700">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {help && <p className="mt-1 text-xs text-gray-500">{help}</p>}
    </div>
  );
}
