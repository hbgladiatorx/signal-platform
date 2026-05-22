"use client";

import { useAuth0 } from "@auth0/auth0-react";

export function LoginButton() {
  const { loginWithRedirect } = useAuth0();

  return (
    <button
      onClick={() =>
        loginWithRedirect({
          appState: { returnTo: "/dashboard" },
        })
      }
      className="rounded-md bg-navy-600 px-4 py-2 text-sm font-medium text-white hover:bg-navy-700 transition-colors"
    >
      Sign in
    </button>
  );
}
