import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";

/**
 * Client-side auth gate. Renders children only when a Supabase session exists.
 * Redirects to /auth otherwise. Used to protect /app and /studio subtrees.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const nav = useNavigate();
  const [status, setStatus] = useState<"checking" | "authed" | "anon">("checking");

  useEffect(() => {
    let active = true;

    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      if (session) setStatus("authed");
      else {
        setStatus("anon");
        nav({ to: "/auth" });
      }
    });

    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      if (data.session) setStatus("authed");
      else {
        setStatus("anon");
        nav({ to: "/auth" });
      }
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
