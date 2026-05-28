import { useEffect, useState } from "react";
import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "@/integrations/supabase/client";
import { setPreferenceScope } from "@/lib/user-prefs";
import { setBillingScope } from "@/lib/api/billing";

export function useAuth() {
  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Subscribe first to avoid races
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      setPreferenceScope(s?.user?.id ?? null);
      setBillingScope(s?.user?.id ?? null);
      setSession(s);
      setUser(s?.user ?? null);
    });

    supabase.auth.getSession().then(({ data }) => {
      setPreferenceScope(data.session?.user?.id ?? null);
      setBillingScope(data.session?.user?.id ?? null);
      setSession(data.session);
      setUser(data.session?.user ?? null);
      setLoading(false);
    });

    return () => sub.subscription.unsubscribe();
  }, []);

  return { session, user, loading };
}
