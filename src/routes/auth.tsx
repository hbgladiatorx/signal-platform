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

              <TabsContent value="signin" className="mt-6">
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
