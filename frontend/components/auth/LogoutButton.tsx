"use client";

import { useAuth0 } from "@auth0/auth0-react";

export function LogoutButton() {
  const { logout } = useAuth0();

  return (
    <button
      onClick={() =>
        logout({
          logoutParams: { returnTo: window.location.origin },
        })
      }
      className="text-sm text-gray-600 hover:text-gray-900 transition-colors"
    >
      Sign out
    </button>
  );
}
