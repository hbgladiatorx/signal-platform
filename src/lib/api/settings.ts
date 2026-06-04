// Settings API — profile, preferences, and API credentials.
// Wired to the FastAPI backend's /settings router. Replaces the hardcoded
// account fields and mock broker toggles in the settings UI.
import { api } from "@/lib/api/client";

export interface Profile {
  user_id: string;
  auth0_sub: string;
  email: string | null;
  name: string | null;
  timezone: string;
  theme: "light" | "dark" | "system";
  notifications_enabled: boolean;
}

export interface ProfileUpdate {
  name?: string | null;
  timezone?: string | null;
  theme?: "light" | "dark" | "system" | null;
  notifications_enabled?: boolean | null;
}

export interface ApiCredential {
  id: string;
  service: string;
  label: string;
  last_four: string | null;
  created_at: string;
  last_used_at: string | null;
}

// Services the backend accepts for /settings/api-keys, with the fields each
// expects (mirrors SERVICE_FIELDS in services/api/routers/settings.py).
export const CREDENTIAL_SERVICES: Array<{
  service: string;
  displayName: string;
  fields: Array<{ key: string; label: string; secret?: boolean }>;
}> = [
  {
    service: "binanceus",
    displayName: "Binance.US",
    fields: [
      { key: "api_key", label: "API key" },
      { key: "secret_key", label: "Secret key", secret: true },
    ],
  },
  {
    service: "alpaca",
    displayName: "Alpaca",
    fields: [
      { key: "api_key_id", label: "API key ID" },
      { key: "secret_key", label: "Secret key", secret: true },
    ],
  },
];

export const getProfile = () => api.get<Profile>("/settings/profile");

export const updateProfile = (body: ProfileUpdate) =>
  api.put<Profile>("/settings/profile", body);

export const getPreferences = () =>
  api.get<{ prefs: Record<string, unknown> }>("/settings/preferences");

export const updatePreferences = (prefs: Record<string, unknown>) =>
  api.put<{ prefs: Record<string, unknown> }>("/settings/preferences", { prefs });

export const listApiCredentials = () =>
  api.get<ApiCredential[]>("/settings/api-keys");

export const createApiCredential = (input: {
  service: string;
  label: string;
  payload: Record<string, string>;
}) => api.post<ApiCredential>("/settings/api-keys", input);

export const deleteApiCredential = (id: string) =>
  api.del<void>(`/settings/api-keys/${id}`);
