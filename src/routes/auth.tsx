import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { ArrowRight, Loader2, ShieldCheck, Mail, Lock } from "lucide-react";

export const Route = createFileRoute("/auth")({
  head: () => ({
    meta: [
      { title: "Sign in — Bayn" },
      { name: "description", content: "Sign in or create a free Bayn account to access verified trading strategies." },
    ],
  }),
  component: AuthPage,
});

function AuthPage() {
  const nav = useNavigate();
  const [tab, setTab] = useState<"signin" | "signup">("signin");
  const [loading, setLoading] = useState(false);

  const handle = (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    // Frontend-only: simulate auth, then redirect.
    setTimeout(() => {
      setLoading(false);
      nav({ to: "/app/home" });
    }, 600);
  };

  return (
    <div
      className="relative grid min-h-screen place-items-center overflow-hidden bg-background px-4 text-foreground"
      style={{ fontFamily: "var(--font-landing-body)" }}
    >
      {/* Background flair */}
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
          <Tabs value={tab} onValueChange={(v) => setTab(v as "signin" | "signup")}>
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="signin">Sign in</TabsTrigger>
              <TabsTrigger value="signup">Create account</TabsTrigger>
            </TabsList>

            <TabsContent value="signin" className="mt-6">
              <form onSubmit={handle} className="space-y-4">
                <Field icon={Mail} label="Email" type="email" placeholder="you@firm.com" required />
                <Field icon={Lock} label="Password" type="password" placeholder="••••••••" required />
                <div className="flex items-center justify-end">
                  <button type="button" className="text-xs text-muted-foreground hover:text-foreground">
                    Forgot password?
                  </button>
                </div>
                <PrimaryButton loading={loading}>
                  Sign in <ArrowRight className="ml-1.5 size-4" />
                </PrimaryButton>
              </form>
            </TabsContent>

            <TabsContent value="signup" className="mt-6">
              <form onSubmit={handle} className="space-y-4">
                <Field icon={Mail} label="Email" type="email" placeholder="you@firm.com" required />
                <Field icon={Lock} label="Password" type="password" placeholder="At least 8 characters" required />
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

          <div className="my-6 flex items-center gap-3 text-[10px] uppercase tracking-wider text-muted-foreground">
            <div className="h-px flex-1 bg-border" />
            or continue with
            <div className="h-px flex-1 bg-border" />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <SocialButton label="Google" />
            <SocialButton label="GitHub" />
          </div>
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

function SocialButton({ label }: { label: string }) {
  return (
    <Button
      type="button"
      variant="outline"
      className="h-11 border-border/80 bg-background/60 hover:bg-background"
      onClick={() => {
        /* frontend-only */
      }}
    >
      {label}
    </Button>
  );
}
