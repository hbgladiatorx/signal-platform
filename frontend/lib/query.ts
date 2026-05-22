import { QueryClient } from "@tanstack/react-query";

/**
 * Centralized TanStack Query configuration.
 *
 * Defaults tuned for a trading platform:
 *   - staleTime: 30s — many endpoints (instruments, settings) don't change often
 *   - retry: 1 — fail fast; retries on a broken backend just delay the error UI
 *   - refetchOnWindowFocus: false — distracting in long-running monitoring views
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: 0,
      },
    },
  });
}
