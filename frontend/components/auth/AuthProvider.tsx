"use client";

import { Auth0Provider } from "@auth0/auth0-react";
import { QueryClientProvider } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { makeQueryClient } from "@/lib/query";

/**
 * Wraps the app in Auth0Provider + QueryClientProvider.
 *
 * Auth0Provider must run on the client (it uses window for redirects),
 * so this component is marked "use client" and is mounted by the root
 * layout. After login, Auth0 redirects to /auth/callback which then
 * sends the user to their original destination.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [queryClient] = useState(() => makeQueryClient());

  const domain = process.env.NEXT_PUBLIC_AUTH0_DOMAIN ?? "";
  const clientId = process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID ?? "";
  const audience = process.env.NEXT_PUBLIC_AUTH0_AUDIENCE ?? "";
  const callbackUrl =
    process.env.NEXT_PUBLIC_AUTH0_CALLBACK_URL ??
    (typeof window !== "undefined"
      ? `${window.location.origin}/auth/callback`
      : "");

  if (!domain || !clientId) {
    return (
      <div className="p-8 text-red-600">
        Auth0 environment variables not set. See frontend/.env.example.
      </div>
    );
  }

  return (
    <Auth0Provider
      domain={domain}
      clientId={clientId}
      authorizationParams={{
        redirect_uri: callbackUrl,
        audience,
      }}
      onRedirectCallback={(appState) => {
        router.replace(appState?.returnTo ?? "/dashboard");
      }}
      cacheLocation="localstorage"
      useRefreshTokens
    >
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </Auth0Provider>
  );
}
