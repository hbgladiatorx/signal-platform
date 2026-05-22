"use client";

/**
 * Auth0 redirects here after successful (or failed) login.
 *
 * The Auth0Provider's onRedirectCallback handles the actual routing
 * to the user's intended destination, so this page just shows a
 * brief loading state while that runs.
 */
export default function AuthCallbackPage() {
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="text-sm text-gray-500">Signing you in…</div>
    </div>
  );
}
