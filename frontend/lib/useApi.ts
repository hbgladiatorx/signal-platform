"use client";

import { useAuth0 } from "@auth0/auth0-react";
import { useMemo } from "react";

import { createApiClient } from "@/lib/api";

/**
 * Hook giving components access to a JWT-authenticated API client.
 *
 * The client lazily fetches the Auth0 access token on each request,
 * which keeps token rotation working without component-level effort.
 */
export function useApi() {
  const { getAccessTokenSilently } = useAuth0();

  return useMemo(
    () =>
      createApiClient(async () => {
        const token = await getAccessTokenSilently({
          authorizationParams: {
            audience: process.env.NEXT_PUBLIC_AUTH0_AUDIENCE,
          },
        });
        return token;
      }),
    [getAccessTokenSilently],
  );
}
