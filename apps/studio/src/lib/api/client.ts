// Typed fetch client for the signal-platform FastAPI backend.
//
// Every studio/app data call goes through here. It:
//   - resolves the API base from VITE_API_BASE (default "/api", same-origin
//     behind Caddy on signal.cimcha.com — Caddy strips /api → api:8000),
//   - attaches the current Supabase session's access token as a Bearer header
//     (the backend verifies it via the Supabase JWKS; see services/api/auth.py),
//   - serializes/parses JSON and normalizes errors into ApiError.
//
// Auth stays with Supabase on the frontend; the backend is the source of truth
// for data. A signed-in user's very first authenticated request lazily
// provisions their backend `users` row, so no explicit registration step.
import { supabase } from "@/integrations/supabase/client";

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Turn a FastAPI `detail` (string | {msg} | validation list) into one line. */
function humanizeDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((e) => {
        const loc = Array.isArray((e as { loc?: unknown[] })?.loc)
          ? (e as { loc: unknown[] }).loc.filter((x) => x !== "body").join(".")
          : "";
        const msg = (e as { msg?: unknown })?.msg;
        const text = typeof msg === "string" ? msg : "invalid";
        return loc ? `${loc}: ${text}` : text;
      })
      .filter(Boolean);
    return parts.length ? parts.join("; ") : null;
  }
  if (detail && typeof detail === "object") {
    const msg = (detail as { msg?: unknown }).msg;
    if (typeof msg === "string") return msg;
  }
  return null;
}

type Query = Record<string, string | number | boolean | undefined | null>;

function buildUrl(path: string, query?: Query): string {
  const url = `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) params.append(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

interface RequestOptions {
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(
  method: string,
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(await authHeaders()),
  };
  const init: RequestInit = { method, headers, signal: opts.signal };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }

  const res = await fetch(buildUrl(path, opts.query), init);

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data
        ? (data as { detail: unknown }).detail
        : data;
    // Surface the backend's real reason. FastAPI sends `detail` as a string, a
    // business-error object like {msg, ...}, OR a request-validation LIST like
    // [{loc, msg, type}]. Unpack all three so a 422 says WHICH field is wrong
    // instead of a generic "Request failed".
    const message = humanizeDetail(detail) ?? `Request failed (${res.status}) ${method} ${path}`;
    throw new ApiError(res.status, message, detail);
  }

  return data as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) =>
    request<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Query) =>
    request<T>("POST", path, { body, query }),
  put: <T>(path: string, body?: unknown, query?: Query) =>
    request<T>("PUT", path, { body, query }),
  del: <T>(path: string, query?: Query) =>
    request<T>("DELETE", path, { query }),
};
