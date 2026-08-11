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

// Shared platform broker keys available to every user (crypto via Binance.US,
// stocks/options via Alpaca). Lets a user deploy without connecting their own.
export interface PlatformCredential {
  id: string;
  service: string;
  label: string;
  last_four: string | null;
  mode: "paper" | "live";
}
export const listPlatformCredentials = () =>
  api.get<PlatformCredential[]>("/settings/platform-credentials");

// AI providers the copilot can run on. Anthropic uses the native API; the rest
// are OpenAI-compatible (base URL + model). Mirrors PRESETS in
// packages/core/ai_provider.py.
export interface AIProviderPreset {
  key: string;
  label: string;
  baseUrl?: string;      // shown/used for OpenAI-compatible providers
  defaultModel: string;  // "" for anthropic (backend picks per feature)
  needsBaseUrl?: boolean; // custom: user must supply the base URL
  hint?: string;
}
export const AI_PROVIDERS: AIProviderPreset[] = [
  { key: "deepseek", label: "DeepSeek (cheapest)", baseUrl: "https://api.deepseek.com/v1", defaultModel: "deepseek-chat", hint: "console: platform.deepseek.com" },
  { key: "anthropic", label: "Anthropic (Claude)", defaultModel: "", hint: "console.anthropic.com" },
  { key: "openai", label: "OpenAI", baseUrl: "https://api.openai.com/v1", defaultModel: "gpt-4o-mini", hint: "platform.openai.com" },
  { key: "groq", label: "Groq (fast)", baseUrl: "https://api.groq.com/openai/v1", defaultModel: "llama-3.3-70b-versatile", hint: "console.groq.com" },
  { key: "openrouter", label: "OpenRouter (many models)", baseUrl: "https://openrouter.ai/api/v1", defaultModel: "openai/gpt-4o-mini", hint: "openrouter.ai/keys" },
  { key: "custom", label: "Custom (OpenAI-compatible)", defaultModel: "", needsBaseUrl: true },
];

export const createApiCredential = (input: {
  service: string;
  label: string;
  payload: Record<string, string>;
}) => api.post<ApiCredential>("/settings/api-keys", input);

export const deleteApiCredential = (id: string) =>
  api.del<void>(`/settings/api-keys/${id}`);
