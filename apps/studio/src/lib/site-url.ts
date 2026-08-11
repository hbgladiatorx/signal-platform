// Canonical public origin for auth redirect links (password reset, signup
// confirmation, OAuth). These links are emailed/handed off and MUST resolve to
// the deployed site — never to a dev `localhost` origin, which would produce a
// dead reset link (the exact failure we hit).
//
// Resolution order:
//   1. VITE_SITE_URL if explicitly configured at build time (staging/self-host).
//   2. The current browser origin — but ONLY if it isn't localhost.
//   3. The production domain, as a hard floor so a link can never be localhost.
const PROD_SITE_URL = "https://signal.cimcha.com";

export function siteUrl(path = ""): string {
  const envUrl = (import.meta.env.VITE_SITE_URL as string | undefined)?.replace(/\/$/, "");
  let base = envUrl || PROD_SITE_URL;

  // With no explicit override, prefer the live origin (so preview/staging
  // domains work), but never localhost — that's what breaks emailed links.
  if (!envUrl && typeof window !== "undefined") {
    const origin = window.location.origin;
    if (origin && !/^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$/i.test(origin)) {
      base = origin;
    }
  }

  if (!path) return base;
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}
