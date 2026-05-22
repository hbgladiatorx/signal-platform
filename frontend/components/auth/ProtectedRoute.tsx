"use client";

import { useAuth0 } from "@auth0/auth0-react";
import { useEffect, type ReactNode } from "react";

/**
 * Wraps a page that requires authentication.
 *
 * If the user is not authenticated, triggers a redirect to Auth0's
 * hosted login page. While Auth0 is checking the session, shows a
 * minimal loading state.
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, loginWithRedirect } = useAuth0();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      loginWithRedirect({
        appState: {
          returnTo:
            typeof window !== "undefined"
              ? window.location.pathname + window.location.search
              : "/dashboard",
        },
      });
    }
  }, [isLoading, isAuthenticated, loginWithRedirect]);

  if (isLoading || !isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-sm text-gray-500">Loading…</div>
      </div>
    );
  }

  return <>{children}</>;
}
