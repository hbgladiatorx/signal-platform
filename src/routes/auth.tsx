import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/auth")({
  head: () => ({ meta: [{ title: "Sign in — Bayn" }, { name: "description", content: "Sign in to Bayn to subscribe to verified trading strategies." }] }),
  component: AuthPage,
});

function AuthPage() {
  const nav = useNavigate();
  const [tab, setTab] = useState<"signin" | "signup">("signin");

  const handle = (e: React.FormEvent) => {
    e.preventDefault();
    // TODO: supabase.auth.signInWithPassword({ email, password })
    nav({ to: "/app/home" });
  };

  return (
    <div className="grid min-h-screen place-items-center bg-background px-4">
      <div className="w-full max-w-md">
        <Link to="/" className="mb-8 flex items-center justify-center gap-2 text-lg font-semibold">
          <div className="grid size-7 place-items-center rounded-md bg-cyan/15 text-cyan font-bold">B</div>
          Bayn
        </Link>
        <Card className="border-border bg-elevated p-6">
          <Tabs value={tab} onValueChange={(v) => setTab(v as "signin" | "signup")}>
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="signin">Sign in</TabsTrigger>
              <TabsTrigger value="signup">Create account</TabsTrigger>
            </TabsList>
            <TabsContent value="signin" className="mt-6">
              <form onSubmit={handle} className="space-y-4">
                <Field label="Email" type="email" placeholder="you@firm.com" />
                <Field label="Password" type="password" placeholder="••••••••" />
                <Button type="submit" className="w-full bg-cyan text-cyan-foreground hover:bg-cyan/90">Sign in</Button>
              </form>
            </TabsContent>
            <TabsContent value="signup" className="mt-6">
              <form onSubmit={handle} className="space-y-4">
                <Field label="Email" type="email" placeholder="you@firm.com" />
                <Field label="Password" type="password" placeholder="At least 8 characters" />
                <Button type="submit" className="w-full bg-cyan text-cyan-foreground hover:bg-cyan/90">Create account</Button>
                <p className="text-center text-xs text-muted-foreground">
                  By signing up you acknowledge Bayn is not investment advice.
                </p>
              </form>
            </TabsContent>
          </Tabs>
        </Card>
      </div>
    </div>
  );
}

function Field({ label, ...props }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <Input {...props} className="bg-background" />
    </div>
  );
}
