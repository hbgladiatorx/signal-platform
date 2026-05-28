import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { getOnboarded, setPreferenceScope } from "@/lib/user-prefs";
import { setBillingScope } from "@/lib/api/billing";
import type { Session } from "@supabase/supabase-js";

/**
 * Client-side auth gate. Renders children only when a Supabase session exists.
 * Redirects unauthenticated users to /auth, and authenticated users that
 * have not completed onboarding to /onboarding. Never wipes prefs — sign-out
 * is the only place that resets local state.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const nav = useNavigate();
  const [status, setStatus] = useState<"checking" | "authed" | "anon">("checking");

  useEffect(() => {
    let active = true;

    const route = (session: Session | null) => {
      setPreferenceScope(session?.user?.id ?? null);
      setBillingScope(session?.user?.id ?? null);
      if (!session) {
        setStatus("anon");
        nav({ to: "/auth" });
        return;
      }
      if (!getOnboarded()) {
        setStatus("checking");
        nav({ to: "/onboarding" });
        return;
      }
      setStatus("authed");
    };

    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      route(session);
    });

    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      route(data.session);
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
