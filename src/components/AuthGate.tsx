import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { getOnboarded, resetAllPrefs } from "@/lib/user-prefs";

/**
 * Client-side auth gate. Renders children only when a Supabase session exists.
 * Redirects unauthenticated users to /auth, and authenticated users that
 * have not completed onboarding to /onboarding.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const nav = useNavigate();
  const [status, setStatus] = useState<"checking" | "authed" | "anon">("checking");

  useEffect(() => {
    let active = true;

    const route = (hasSession: boolean) => {
      if (!hasSession) {
        setStatus("anon");
        nav({ to: "/auth" });
        return;
      if (!getOnboarded()) {
        // Authenticated but never completed onboarding. Wipe any leftover
        // local state (stale follows, demo seeds) so the user starts blank,
        // then send them through the guided flow.
        resetAllPrefs();
        setStatus("checking");
        nav({ to: "/onboarding" });
        return;
      }
      setStatus("authed");
    };

    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      route(!!session);
    });

    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      route(!!data.session);
    });

    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, [nav]);

  if (status !== "authed") {
    return (
      <div className="grid min-h-screen place-items-center bg-background">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return <>{children}</>;
}
