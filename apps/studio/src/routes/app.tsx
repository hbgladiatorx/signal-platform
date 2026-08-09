import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/layout/AppShell";
import { AuthGate } from "@/components/AuthGate";

export const Route = createFileRoute("/app")({
  component: () => (
    <AuthGate>
      <AppShell mode="trader" />
    </AuthGate>
  ),
});
