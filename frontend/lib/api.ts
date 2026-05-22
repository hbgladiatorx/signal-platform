/**
 * API client.
 *
 * All requests to the backend go through `apiFetch`. It attaches the
 * Auth0 JWT, throws on non-2xx responses with parsed error detail,
 * and returns the parsed JSON body.
 *
 * The caller provides a `getAccessToken` function (typically from the
 * Auth0 hook) so we never store tokens in module state.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public path: string,
  ) {
    super(`${status} ${path}: ${detail}`);
    this.name = "ApiError";
  }
}

type GetAccessToken = () => Promise<string>;

export interface ApiClient {
  get: <T>(path: string) => Promise<T>;
  post: <T>(path: string, body: unknown) => Promise<T>;
  put: <T>(path: string, body: unknown) => Promise<T>;
  delete: <T>(path: string) => Promise<T>;
}

export function createApiClient(getAccessToken: GetAccessToken): ApiClient {
  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const token = await getAccessToken();
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    if (!res.ok) {
      let detail = res.statusText;
      try {
        const errBody = await res.json();
        if (typeof errBody === "object" && errBody && "detail" in errBody) {
          detail = String((errBody as { detail: unknown }).detail);
        }
      } catch {
        /* response wasn't JSON, fall back to statusText */
      }
      throw new ApiError(res.status, detail, path);
    }

    if (res.status === 204) {
      return undefined as T;
    }

    return res.json() as Promise<T>;
  }

  return {
    get: (path) => request("GET", path),
    post: (path, body) => request("POST", path, body),
    put: (path, body) => request("PUT", path, body),
    delete: (path) => request("DELETE", path),
  };
}
