import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { ArrowRight, Loader2, ShieldCheck, Mail, Lock, ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";
import { getOnboarded, resetAllPrefs, setPreferenceScope } from "@/lib/user-prefs";
import { resetCurrentPlan, setBillingScope } from "@/lib/api/billing";

export const Route = createFileRoute("/auth")({
  head: () => ({
    meta: [
      { title: "Sign in — Bayn" },
      { name: "description", content: "Sign in or create a free Bayn account to access verified trading strategies." },
    ],
  }),
  component: AuthPage,
});

type Mode = "signin" | "signup" | "forgot";

function AuthPage() {
  const nav = useNavigate();
  const [mode, setMode] = useState<Mode>("signin");
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // If already signed in, bounce into the app (or onboarding if not yet completed).
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setPreferenceScope(data.session?.user?.id ?? null);
      setBillingScope(data.session?.user?.id ?? null);
      if (data.session) nav({ to: getOnboarded() ? "/app/home" : "/onboarding" });
    });
  }, [nav]);


  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) return toast.error(error.message);
    setPreferenceScope(data.session?.user?.id ?? null);
    setBillingScope(data.session?.user?.id ?? null);
    toast.success("Welcome back");
    nav({ to: getOnboarded() ? "/app/home" : "/onboarding" });
  };


  const handleSignUp = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: window.location.origin },
    });
    setLoading(false);
    if (error) return toast.error(error.message);
    // Brand-new account: wipe any prefs/plan left over from a previous
    // session in this browser so the user always goes through onboarding fresh.
    resetAllPrefs();
    resetCurrentPlan();
    const { data } = await supabase.auth.getSession();
    setPreferenceScope(data.session?.user?.id ?? null);
    setBillingScope(data.session?.user?.id ?? null);
    if (data.session) {
      resetAllPrefs();
      resetCurrentPlan();
      toast.success("Account created");
      nav({ to: "/onboarding" });
    } else {
      toast.success("Check your email to confirm your account");
    }
  };

  const handleForgot = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/reset-password`,
    });
    setLoading(false);
    if (error) return toast.error(error.message);
    toast.success("Password reset email sent");
    setMode("signin");
  };

  const handleGoogle = async () => {
    setLoading(true);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/auth` },
    });
    if (error) { setLoading(false); toast.error(error.message); }
  };


  return (
    <div
      className="relative grid min-h-screen place-items-center overflow-hidden bg-background px-4 text-foreground"
      style={{ fontFamily: "var(--font-landing-body)" }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 70% 50% at 50% 0%, color-mix(in oklab, var(--emerald) 22%, transparent), transparent 70%), radial-gradient(ellipse 60% 50% at 80% 90%, color-mix(in oklab, var(--brand-gold) 10%, transparent), transparent 70%)",
        }}
      />

      <div className="relative w-full max-w-md">
        <Link to="/" className="mb-8 flex items-center justify-center gap-2.5 text-lg font-semibold">
          <div
            className="grid size-8 place-items-center rounded-lg font-bold text-brand-cream"
            style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}
          >
            B
          </div>
          <span style={{ fontFamily: "var(--font-landing-display)", letterSpacing: "-0.02em" }}>Bayn</span>
        </Link>

        <Card
          className="border-border/80 bg-elevated/80 p-6 backdrop-blur-xl md:p-7"
          style={{ boxShadow: "0 20px 60px -20px rgba(0,0,0,0.4)" }}
        >
          {mode === "forgot" ? (
            <form onSubmit={handleForgot} className="space-y-4">
              <button
                type="button"
                onClick={() => setMode("signin")}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <ArrowLeft className="size-3.5" /> Back to sign in
              </button>
              <div>
                <h2 className="text-lg font-semibold" style={{ fontFamily: "var(--font-landing-display)" }}>
                  Reset your password
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  We'll send a reset link to your email.
                </p>
              </div>
              <Field icon={Mail} label="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@firm.com" />
              <PrimaryButton loading={loading}>
                Send reset link <ArrowRight className="ml-1.5 size-4" />
              </PrimaryButton>
            </form>
          ) : (
            <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)}>
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="signin">Sign in</TabsTrigger>
                <TabsTrigger value="signup">Create account</TabsTrigger>
              </TabsList>

              <div className="mt-6 space-y-3">
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleGoogle}
                  disabled={loading}
                  className="h-11 w-full gap-2"
                >
                  <svg className="size-4" viewBox="0 0 24 24" aria-hidden>
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.99.66-2.25 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.83z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.83C6.71 7.31 9.14 5.38 12 5.38z"/>
                  </svg>
                  Continue with Google
                </Button>
                <div className="flex items-center gap-3 text-[10px] uppercase tracking-wider text-muted-foreground">
                  <div className="h-px flex-1 bg-border" /> or email <div className="h-px flex-1 bg-border" />
                </div>
              </div>

              <TabsContent value="signin" className="mt-4">

                <form onSubmit={handleSignIn} className="space-y-4">
                  <Field icon={Mail} label="Email" type="email" placeholder="you@firm.com" required value={email} onChange={(e) => setEmail(e.target.value)} />
                  <Field icon={Lock} label="Password" type="password" placeholder="••••••••" required value={password} onChange={(e) => setPassword(e.target.value)} />
                  <div className="flex items-center justify-end">
                    <button
                      type="button"
                      onClick={() => setMode("forgot")}
                      className="text-xs text-muted-foreground hover:text-foreground"
                    >
                      Forgot password?
                    </button>
                  </div>
                  <PrimaryButton loading={loading}>
                    Sign in <ArrowRight className="ml-1.5 size-4" />
                  </PrimaryButton>
                </form>
              </TabsContent>

              <TabsContent value="signup" className="mt-6">
                <form onSubmit={handleSignUp} className="space-y-4">
                  <Field icon={Mail} label="Email" type="email" placeholder="you@firm.com" required value={email} onChange={(e) => setEmail(e.target.value)} />
                  <Field icon={Lock} label="Password" type="password" placeholder="At least 8 characters" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
                  <PrimaryButton loading={loading}>
                    Create free account <ArrowRight className="ml-1.5 size-4" />
                  </PrimaryButton>
                  <p className="text-center text-[11px] leading-relaxed text-muted-foreground">
                    By signing up you acknowledge Bayn provides information, not investment advice. You stay in
                    control of every trade.
                  </p>
                </form>
              </TabsContent>
            </Tabs>
          )}
        </Card>

        <p className="mt-6 flex items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
          <ShieldCheck className="size-3.5 text-emerald-glow" />
          We never connect to your broker. Bayn cannot trade for you.
        </p>
      </div>
    </div>
  );
}

function Field({
  icon: Icon,
  label,
  ...props
}: { icon: React.ComponentType<{ className?: string }>; label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs uppercase tracking-wider text-muted-foreground">{label}</Label>
      <div className="relative">
        <Icon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input {...props} className="h-11 bg-background pl-9" />
      </div>
    </div>
  );
}

function PrimaryButton({ children, loading }: { children: React.ReactNode; loading: boolean }) {
  return (
    <Button
      type="submit"
      disabled={loading}
      className="h-11 w-full text-brand-cream"
      style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : children}
    </Button>
  );
}
