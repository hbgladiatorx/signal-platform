import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { ArrowRight, Loader2, Lock } from "lucide-react";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";

export const Route = createFileRoute("/reset-password")({
  head: () => ({
    meta: [
      { title: "Reset password — Bayn" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: ResetPasswordPage,
});

function ResetPasswordPage() {
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Supabase appends a recovery token to the URL hash; the client picks it up
    // automatically via detectSessionInUrl. Wait for a session to exist.
    const { data: sub } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY" || event === "SIGNED_IN") setReady(true);
    });
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) setReady(true);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirm) return toast.error("Passwords don't match");
    if (password.length < 8) return toast.error("Password must be at least 8 characters");
    setLoading(true);
    const { error } = await supabase.auth.updateUser({ password });
    setLoading(false);
    if (error) return toast.error(error.message);
    toast.success("Password updated");
    nav({ to: "/app/home" });
  };

  return (
    <div className="grid min-h-screen place-items-center bg-background px-4 text-foreground" style={{ fontFamily: "var(--font-landing-body)" }}>
      <div className="w-full max-w-md">
        <Link to="/" className="mb-8 flex items-center justify-center gap-2.5 text-lg font-semibold">
          <div className="grid size-8 place-items-center rounded-lg font-bold text-brand-cream" style={{ background: "var(--gradient-emerald)" }}>B</div>
          <span style={{ fontFamily: "var(--font-landing-display)" }}>Bayn</span>
        </Link>
        <Card className="border-border/80 bg-elevated/80 p-6 backdrop-blur-xl md:p-7">
          <h1 className="text-lg font-semibold" style={{ fontFamily: "var(--font-landing-display)" }}>
            Set a new password
          </h1>
          {!ready ? (
            <p className="mt-4 text-sm text-muted-foreground">
              Verifying your reset link…
            </p>
          ) : (
            <form onSubmit={handleSubmit} className="mt-5 space-y-4">
              <PasswordField label="New password" value={password} onChange={setPassword} />
              <PasswordField label="Confirm password" value={confirm} onChange={setConfirm} />
              <Button
                type="submit"
                disabled={loading}
                className="h-11 w-full text-brand-cream"
                style={{ background: "var(--gradient-emerald)", boxShadow: "var(--shadow-emerald)" }}
              >
                {loading ? <Loader2 className="size-4 animate-spin" /> : (<>Update password <ArrowRight className="ml-1.5 size-4" /></>)}
              </Button>
            </form>
          )}
        </Card>
      </div>
    </div>
  );
}

function PasswordField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs uppercase tracking-wider text-muted-foreground">{label}</Label>
      <div className="relative">
        <Lock className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input type="password" required minLength={8} value={value} onChange={(e) => onChange(e.target.value)} className="h-11 bg-background pl-9" />
      </div>
    </div>
  );
}
